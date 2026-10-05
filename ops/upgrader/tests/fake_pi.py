#!/usr/bin/env python3
"""Stands in for pi. FAKE_PI selects what the session does."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

args = sys.argv[1:]
if args == ["--version"]:
    print("0.85.1")
    sys.exit(0)
if args[:1] == ["--export"]:
    Path(args[2]).write_text("<html>" + Path(args[1]).read_text() + "</html>")
    sys.exit(0)

GIT = shutil.which("git", path="/usr/local/bin:/usr/bin")
mode = os.environ.get("FAKE_PI", "result:up_to_date")
slug = os.environ["UPGRADE_PRODUCT"]
dry = os.environ["UPGRADE_DRY_RUN"] != "0"
out = Path(os.environ["UPGRADE_OUT_DIR"]) / slug
out.mkdir(parents=True, exist_ok=True)
token = Path(os.environ["UPGRADER_TOKEN_FILE"]).read_text()

session_dir = Path(args[args.index("--session-dir") + 1])
session_dir.mkdir(parents=True, exist_ok=True)
resumed = "--session" in args
transcript = Path(args[args.index("--session") + 1]) if resumed else session_dir / "2026-09-15T03-00-00-000Z_fake.jsonl"
usage = {"input": 1000, "output": 200, "cacheRead": 500}
with transcript.open("a" if resumed else "w") as f:
    f.write(json.dumps({"type": "session", "cwd": os.getcwd()}) + "\n")
    f.write(json.dumps({"type": "message", "message": {
        "role": "assistant", "usage": usage,
        "content": [{"type": "text", "text": f"GH_TOKEN={token} key={os.environ.get('INFERENCE_API_KEY')}"}],
    }}) + "\n")
    f.flush()
print(f"env has key: {'GITHUB_APP_PRIVATE_KEY' in os.environ}; token {token}", flush=True)
print(f"prompt: {args[-1]}", flush=True)
Path(os.environ["FAKE_PI_ENV"]).write_text(json.dumps(dict(os.environ))) if "FAKE_PI_ENV" in os.environ else None
if "FAKE_PI_STAT" in os.environ:
    seen = {name: [os.stat(name).st_uid, os.stat(name).st_gid, oct(os.stat(name).st_mode & 0o7777)]
            for name in (".", "runner", "agent", "session", "out", "freepod")}
    try:
        os.listdir("runner")
        seen["runner_listed"] = True
    except PermissionError:
        seen["runner_listed"] = False
    Path(os.environ["FAKE_PI_STAT"]).write_text(json.dumps(seen))

if mode == "sleep":
    child = subprocess.Popen(["sleep", "600"])
    Path(os.environ["FAKE_PI_CHILD"]).write_text(str(child.pid))
    time.sleep(600)
if mode == "unwritable":
    locked = Path("out") / "locked"
    locked.mkdir()
    (locked / "inside").write_text("x")
    locked.chmod(0o500)
    mode = "result:up_to_date"


def git(*a):
    subprocess.run([GIT, "-c", "user.name=Erik", "-c", "user.email=erik@example.com", *a],
                   cwd="freepod", check=True, capture_output=True)


def propose(path, body):
    """Commit a change to `path` in the session's clone and write the would-be pull request."""
    git("checkout", "-q", "-f", "-B", f"upgrade/{slug}-1.37.3", "master")
    target = Path("freepod") / path
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a") as f:
        f.write("# upgraded\n")
    git("add", path)
    git("commit", "-q", "-m", f"{slug}: Upgrade to 1.37.3")
    patch = subprocess.run([GIT, "format-patch", "--stdout", "HEAD~1..HEAD"], cwd="freepod",
                           check=True, capture_output=True).stdout
    (out / "change.patch").write_bytes(patch)
    (out / "body.md").unlink(missing_ok=True)
    (out / "body.md").write_text(body)
    (out / "meta.json").write_text(json.dumps({"title": f"{slug.capitalize()}: Upgrade to 1.37.3"}))


result = {
    "schema_version": 2, "product": slug, "dry_run": dry, "status": "up_to_date",
    "current_version": "1.37.1", "target_version": None, "draft": False, "needs_human": [],
}
if mode == "repairable" and resumed:
    mode = "result:up_to_date"
if mode == "repairable":
    result["schema_version"] = 1
if mode == "none":
    sys.exit(0)
if mode == "malformed":
    (out / "result.json").write_text("{not json")
    sys.exit(0)
if mode == "wrong-product":
    result["product"] = "nextcloud"
if mode == "dry-mismatch":
    result["dry_run"] = not dry
if mode == "opened":
    result.update(status="opened", target_version="1.37.3", branch=f"upgrade/{slug}-1.37.3",
                  pr_url="https://github.com/erikvanzijst/freepod/pull/200")
if mode == "tampered-schema":
    schema = Path("freepod/products/UPGRADING/result.schema.json")
    schema.write_text(json.dumps({"type": "object"}))
    result.update(status="opened", pr_url="https://github.com/erikvanzijst/freepod/pull/200")
if mode.startswith("propose:"):
    kind = mode.split(":", 1)[1]
    if resumed:
        kind = "ok"
    path, body = f"products/catalog/{slug}.yaml", f"## Summary\nUpgrade {slug}. token {token}\n"
    if kind == "other-product":
        path = "products/catalog/nextcloud.yaml"
    if kind == "workflow":
        path = ".github/workflows/ci.yml"
    if kind == "link":
        body += "Fixes https://github.com/dani-garcia/vaultwarden/issues/123\n"
    if kind == "mention":
        body += "Thanks @dani-garcia, and `@bitwarden/sdk` is fine.\n"
    propose(path, body)
    if kind == "symlink-body":
        (out / "body.md").unlink()
        (out / "body.md").symlink_to(os.environ["FAKE_PI_SECRET"])
    result.update(status="would_open", target_version="1.37.3", branch=f"upgrade/{slug}-1.37.3",
                  draft=True, needs_human=["Check the invite fix"])
if mode.startswith("result:"):
    status = mode.split(":", 1)[1]
    result["status"] = status
    if status == "would_skip":
        propose(f"products/catalog/{slug}.yaml", f"## Summary\nUpgrade {slug}.\n")
        result.update(target_version="1.37.3", branch=f"upgrade/{slug}-1.37.3", draft=True,
                      skip_reason="PR #150 already sets 1.37.3")
    if status == "skipped":
        result["skip_reason"] = f"no image; token {token}"
(out / "result.json").write_text(json.dumps(result))
