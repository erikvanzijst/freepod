"""A session's proposed pull request: checked in both modes, published by the service in a real
run (D4, product-upgrade-runs). The patch is applied to the service's own clone; nothing of the
session's clone is ever run, fetched or pushed."""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from . import untrusted
from .result import ResultError, parse_result, summary

MAX_BODY_CHARS = 65536
MAX_FILE = 1024 * 1024
MAX_META = 64 * 1024
LINK = re.compile(r"github\.com/[^ ]+/(pull|issues)/[0-9]+")
FENCE = re.compile(r"^(```|~~~).*?^\1", re.S | re.M)
CODE_SPAN = re.compile(r"(`+)(?!`).*?(?<!`)\1(?!`)", re.S)
MENTION = re.compile(r"(?<![\w`])@[A-Za-z0-9]")
SPECIAL_MODES = {"120000": "a symbolic link", "160000": "a submodule"}


@dataclass(frozen=True)
class Proposal:
    slug: str
    branch: str
    title: str
    body: str
    patch: bytes
    draft: bool


def load(workspace: Path, out: str, doc: dict, owner: int) -> Proposal:
    """The proposal a `would_open` result points at, from the session's output directory."""
    slug = doc["product"]

    def get(name: str, limit: int) -> bytes:
        data = untrusted.read(workspace, f"{out}/{slug}/{name}", owner, limit)
        if data is None:
            raise ResultError(f"{name} is missing, not a regular file, or larger than {limit} bytes")
        return data

    try:
        meta = json.loads(get("meta.json", MAX_META))
        body = get("body.md", MAX_FILE).decode()
    except (ValueError, UnicodeDecodeError) as exc:
        raise ResultError(f"meta.json or body.md is unreadable: {exc}") from exc
    title = meta.get("title") if isinstance(meta, dict) else None
    if not isinstance(title, str):
        raise ResultError('meta.json must be an object with a string "title"')
    return Proposal(slug, doc["branch"], title, body, get("change.patch", MAX_FILE), bool(doc["draft"]))


def check_text(p: Proposal, target: str) -> None:
    if p.branch != f"upgrade/{p.slug}-{target}":
        raise ResultError(f"branch must be upgrade/{p.slug}-{target}, not {p.branch!r}")
    if not re.fullmatch(rf"[^\n]{{1,200}}: Upgrade to {re.escape(target)}", p.title):
        raise ResultError(f"meta.json title must be one line, '<Product>: Upgrade to {target}'")
    if len(p.body) > MAX_BODY_CHARS:
        raise ResultError(f"body.md is {len(p.body)} characters; GitHub accepts {MAX_BODY_CHARS}")
    if m := LINK.search(p.body):
        raise ResultError(f"body.md links an issue or pull request ({m.group(0)}); "
                          "follow the skill's Changelog sanitization")
    prose = CODE_SPAN.sub("", FENCE.sub("", p.body))
    if m := MENTION.search(prose):
        line = prose[: m.start()].count("\n") + 1
        raise ResultError(f"body.md has an @ outside backticks near line {line} of its prose; "
                          "follow the skill's Changelog sanitization")
    if not p.patch.strip():
        raise ResultError("change.patch is empty")


class Clone:
    """The service's own clone of master, where proposals are applied."""

    def __init__(self, path: Path, git: str, env: Mapping[str, str]):
        self.path, self.git, self.env = path, git, dict(env)

    def run(self, *args: str, stdin: bytes | None = None, env: Mapping[str, str] | None = None,
            check: bool = True) -> str:
        out = subprocess.run([self.git, "-c", "core.hooksPath=/dev/null", *args], cwd=self.path,
                             input=stdin, capture_output=True, timeout=600,
                             env={**self.env, **(env or {})})
        if check and out.returncode:
            raise RuntimeError(f"git {args[0]} failed: {out.stderr.decode(errors='replace').strip()[-500:]}")
        return out.stdout.decode(errors="replace").strip()

    def apply(self, p: Proposal) -> str:
        """Commit the patch on `p.branch`, on top of master as it is now, and check what it
        changes. Returns the base commit. Refusals are the session's to fix."""
        if subprocess.run([self.git, "check-ref-format", "--branch", p.branch],
                          capture_output=True).returncode:
            raise ResultError(f"{p.branch!r} is not a valid branch name")
        self.run("fetch", "-q", "--depth", "1", "origin", "master")
        base = self.run("rev-parse", "FETCH_HEAD")
        self.run("checkout", "-q", "-f", "-B", p.branch, base)
        applied = subprocess.run(
            [self.git, "-c", "core.hooksPath=/dev/null", "am", "-q", "--no-3way", "--keep-cr"],
            cwd=self.path, input=p.patch, capture_output=True, timeout=600, env=self.env)
        if applied.returncode:
            self.run("am", "--abort", check=False)
            detail = (applied.stdout + applied.stderr).decode(errors="replace").strip()[-400:]
            raise ResultError(f"change.patch does not apply to master: {detail}")
        if self.run("rev-parse", "HEAD") == base:
            raise ResultError("change.patch holds no commits")
        allowed = (f"products/catalog/{p.slug}.yaml", f"products/{p.slug}/")
        raw = self.run("diff", "--raw", "--no-renames", "-z", base, "HEAD")
        fields = raw.split("\0")
        for meta, path in zip(fields[0::2], fields[1::2]):
            modes = meta.lstrip(":").split()[:2]
            if path != allowed[0] and not path.startswith(allowed[1]):
                raise ResultError(
                    f"change.patch changes {path}, outside {allowed[0]} and {allowed[1]}")
            for mode in modes:
                if mode in SPECIAL_MODES:
                    raise ResultError(f"change.patch makes {path} {SPECIAL_MODES[mode]}")
        return base

    def publish(self, p: Proposal, base: str, identity: tuple[str, str], token: str,
                repo_url: str) -> None:
        """Author the commits as the App's bot and push the branch, which must not exist yet."""
        name, email = identity
        who = {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
               "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email}
        amend = "git commit -q --amend --no-edit --no-verify --reset-author"
        self.run("rebase", "-q", "--force-rebase", "--exec", amend, base, env=who)
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        header = {"GIT_CONFIG_COUNT": "2",
                  "GIT_CONFIG_KEY_0": "credential.helper", "GIT_CONFIG_VALUE_0": "",
                  "GIT_CONFIG_KEY_1": "http.https://github.com/.extraheader",
                  "GIT_CONFIG_VALUE_1": f"AUTHORIZATION: basic {basic}"}
        ref = f"refs/heads/{p.branch}"
        # The lease refuses a branch that exists, but git skips it when the push changes nothing.
        if self.run("ls-remote", repo_url, ref, env=header):
            raise RuntimeError(f"push failed: {p.branch} already exists on {repo_url}")
        self.run("push", "-q", "--no-verify", f"--force-with-lease={ref}:", repo_url, f"HEAD:{ref}",
                 env=header)


def main(argv: list[str]) -> int:
    """`python -m upgrader.proposal SCHEMA OUT_DIR SLUG REPO_URL`: the local runner's check of one
    dry-run session, with the service's checks, its proposal applied to a fresh clone."""
    schema, out_dir, slug, repo_url = argv
    out, owner = Path(out_dir), os.getuid()
    work = Path(tempfile.mkdtemp(prefix=f"proposal-{slug}-"))
    try:
        doc = parse_result(untrusted.read(out, f"{slug}/result.json", owner, MAX_META), Path(schema),
                           slug, dry_run=True)
        if doc["status"] == "would_open":
            if not doc.get("target_version"):
                raise ResultError("a would_open result needs its target_version")
            proposal = load(out, ".", doc, owner)
            check_text(proposal, doc["target_version"])
            git = shutil.which("git") or "git"
            subprocess.run([git, "clone", "-q", "--depth", "1", "--branch", "master", repo_url,
                            str(work / "freepod")], check=True, capture_output=True, timeout=600)
            Clone(work / "freepod", git, os.environ).apply(proposal)
    except ResultError as exc:
        print(f"{slug}: failed: {exc}")
        return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(summary(doc))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
