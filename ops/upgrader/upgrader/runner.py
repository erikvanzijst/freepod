"""Executing a run: its products, one at a time, each in a fresh session and clone
(product-upgrade-runs, product-upgrade-history)."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import BinaryIO

from sqlalchemy.orm import sessionmaker

from . import notify, pi, untrusted
from .agent import Agent
from .cancel import Cancellation
from .catalog import fetch
from .config import REPO, Settings
from .db import ProductResult, Run, now
from .github import READ_ONLY, READ_WRITE, App, TokenFile
from .live import Live
from .live import Session as LiveSession
from .proposal import Clone, Proposal, check_text, load
from .redact import Redactor
from .result import ResultError, parse_result
from .store import CONTENT_TYPES, product_prefix

log = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parents[1]
PRIVATE_ENV = (
    "GITHUB_APP_PRIVATE_KEY", "SMTP_PASS", "DATABASE_URL", "BUCKET_NAME", "GH_TOKEN", "GITHUB_TOKEN",
)
PRIVATE_PREFIXES = ("PG", "AWS_", "S3_")
RESULT_FILES = ("result.json", "body.md", "change.patch")
SCHEMA = Path("products/UPGRADING/result.schema.json")
MAX_RESULT = 64 * 1024
MAX_FILE = 1024 * 1024
MAX_TRANSCRIPT = 64 * 1024 * 1024
# The workspace (D2). The service's own directory is closed to the session; the shared ones
# belong to the service, so the session can fill them but not swap them for links, and the
# sticky root keeps it from replacing anything the service put there.
RUNNER, SHARED, CLONE = "runner", ("agent", "session", "out"), "freepod"


@dataclass
class Deps:
    Session: sessionmaker
    store: object
    settings: Callable[[], Settings] = Settings.from_env
    github: Callable[[Settings], App] = lambda s: App(s.github_app_id, s.github_app_private_key)
    pi: str = "pi"
    git: str = shutil.which("git") or "git"
    guards: Path = HERE / "bin"
    git_config: Path = field(
        default_factory=lambda: Path(os.environ.get("GIT_CONFIG_SYSTEM", "/etc/gitconfig")))
    workdir: Path = Path(tempfile.gettempdir())
    state_dir: Path = Path(tempfile.gettempdir()) / "upgrader"
    smtp: Callable | None = None
    poll_seconds: float = 15
    extra_env: dict[str, str] = field(default_factory=dict)
    live: Live = field(default_factory=Live)
    cancel: Cancellation = field(default_factory=Cancellation)
    agent: Agent = field(default_factory=Agent.named)


@dataclass(frozen=True)
class Accepted:
    """A result that passed every check, with the proposal it points at, if any, applied to the
    service's clone on top of `base`."""

    doc: dict
    proposal: Proposal | None = None
    base: str | None = None


def _git(deps: Deps, *args: str, cwd: Path | None = None) -> str:
    out = subprocess.run([deps.git, *args], cwd=cwd, capture_output=True, text=True, timeout=600)
    if out.returncode:
        raise RuntimeError(f"git {args[0]} failed: {out.stderr.strip()[-500:]}")
    return out.stdout.strip()


def _clone(deps: Deps, settings: Settings, into: Path) -> str:
    _git(deps, "clone", "-q", "--depth", "1", "--branch", "master", settings.repo_url, str(into))
    return _git(deps, "rev-parse", "HEAD", cwd=into)


def _agent_clone(deps: Deps, settings: Settings, workspace: Path) -> None:
    env = {"PATH": os.environ.get("PATH", os.defpath), "HOME": deps.agent.home,
           "GIT_CONFIG_SYSTEM": str(deps.git_config)}
    out = deps.agent.run([deps.git, "clone", "-q", "--depth", "1", "--branch", "master",
                          settings.repo_url, str(workspace / CLONE)], env=env, cwd=workspace,
                         capture_output=True, text=True, timeout=600)
    if out.returncode:
        raise RuntimeError(f"the session's clone failed: {out.stderr.strip()[-500:]}")


def _update(deps: Deps, row_id: int, **values) -> None:
    with deps.Session.begin() as session:
        row = session.get(ProductResult, row_id)
        for key, value in values.items():
            setattr(row, key, value)


def run_url(settings: Settings, run_id: int, slug: str) -> str:
    """The product's place on the dashboard, which the session links to from the pull request.
    The run page rather than a stored file, because a signed file link expires within the hour
    and a reviewer reads the pull request long after the run wrote it. Empty when the
    deployment has no public URL configured, and then the description carries no link."""
    if not settings.dashboard_url:
        return ""
    return f"{settings.dashboard_url.rstrip('/')}/runs/{run_id}#{slug}"


def session_env(deps: Deps, settings: Settings, slug: str, workspace: Path, token_file: Path,
                agent_dir: Path, url: str = "") -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if k not in PRIVATE_ENV and not k.startswith(PRIVATE_PREFIXES)}
    env.update(deps.extra_env)
    env.update(
        PATH=f"{deps.guards}{os.pathsep}{os.environ.get('PATH', os.defpath)}",
        HOME=deps.agent.home,
        PI_CODING_AGENT_DIR=str(agent_dir),
        PI_TELEMETRY="0",
        INFERENCE_API_KEY=settings.inference_api_key or "",
        UPGRADE_PRODUCT=slug,
        UPGRADE_DRY_RUN="1" if settings.dry_run else "0",
        UPGRADE_OUT_DIR=str(workspace / "out"),
        UPGRADE_RUN_URL=url,
        UPGRADER_TOKEN_FILE=str(token_file),
        GH_REPO=REPO,
        GIT_CONFIG_SYSTEM=str(deps.git_config),
    )
    return env


def _prepare(deps: Deps, settings: Settings, workspace: Path) -> None:
    """Lay out the workspace (D2) before any of the session user's processes start."""
    (workspace / RUNNER).mkdir(mode=0o700)
    for name in SHARED:
        (workspace / name).mkdir()
        deps.agent.share(workspace / name, 0o2770)
    pi.write_agent_dir(workspace / "agent", settings).joinpath("models.json").chmod(0o644)
    deps.agent.share(workspace, 0o1770)


def _run_session(deps: Deps, settings: Settings, workspace: Path, env: dict[str, str], tokens: TokenFile,
                 slug: str, clone: Clone) -> tuple[str, Accepted | ResultError | None]:
    """Run pi until it exits, times out, or the run is canceled. Returns the outcome the service
    assigns itself, or "" when the session ended on its own, and then the judged result. A
    session that ends on its own with an unacceptable result gets one more turn, within the
    same deadline, to fix it."""
    skill = workspace / CLONE / "products" / "UPGRADING" / "SKILL.md"
    deadline = time.monotonic() + settings.timeout_seconds
    with (workspace / RUNNER / "stdout.txt").open("wb") as stdout:
        cmd = pi.command(settings, skill, workspace / "session", pi.prompt(slug), pi=deps.pi)
        if ended := _run_pi(deps, workspace, env, tokens, slug, cmd, stdout, deadline):
            return ended, None
        try:
            return "", _judge(deps, settings, workspace, slug, clone)
        except ResultError as exc:
            problem = exc
        transcript = _transcript(deps, workspace)
        if not transcript:
            return "", problem
        log.info("asking %s's session to fix its result: %s", slug, problem)
        cmd = pi.command(settings, skill, workspace / "session", pi.repair_prompt(slug, str(problem)),
                         pi=deps.pi, resume=workspace / transcript)
        if ended := _run_pi(deps, workspace, env, tokens, slug, cmd, stdout, deadline):
            return ended, None
        try:
            return "", _judge(deps, settings, workspace, slug, clone)
        except ResultError as exc:
            return "", exc


def _run_pi(deps: Deps, workspace: Path, env: dict[str, str], tokens: TokenFile, slug: str,
            cmd: list[str], stdout: BinaryIO, deadline: float) -> str:
    process = deps.agent.popen(cmd, env, cwd=workspace, stdin=subprocess.DEVNULL, stdout=stdout,
                               stderr=subprocess.STDOUT, start_new_session=True)
    ended = "" if deps.cancel.watch(lambda: deps.agent.interrupt(process)) else "canceled"
    try:
        while not ended:
            try:
                process.wait(timeout=max(0.01, min(deps.poll_seconds, deadline - time.monotonic())))
                break
            except subprocess.TimeoutExpired:
                if deps.cancel.asked():
                    ended = "canceled"
                elif time.monotonic() >= deadline:
                    ended = "timed_out"
                else:
                    try:
                        tokens.refresh()
                    except Exception:
                        log.exception("could not refresh the installation token for %s", slug)
        # A cancel ends the session itself, so the wait above returns rather than timing
        # out: without this the product would be read as one that wrote no result.
        if not ended and deps.cancel.asked():
            ended = "canceled"
    finally:
        deps.cancel.watch(None)
        deps.agent.terminate(process)
    return ended


def _transcript(deps: Deps, workspace: Path) -> str | None:
    return next(iter(untrusted.find(workspace, "session", ".jsonl", deps.agent.uid)), None)


def _judge(deps: Deps, settings: Settings, workspace: Path, slug: str, clone: Clone) -> Accepted:
    """The session's result, checked against the service's own copy of the contract, and its
    proposal checked and applied to the service's clone. Raises ResultError for anything the
    session can fix."""
    raw = untrusted.read(workspace, f"out/{slug}/result.json", deps.agent.uid, MAX_RESULT)
    doc = parse_result(raw, clone.path / SCHEMA, slug, settings.dry_run)
    if doc["status"] != "would_open":
        return Accepted(doc)
    if not doc.get("target_version"):
        raise ResultError("a would_open result needs its target_version")
    proposal = load(workspace, "out", doc, deps.agent.uid)
    check_text(proposal, doc["target_version"])
    return Accepted(doc, proposal, clone.apply(proposal))


def _store_files(deps: Deps, run_id: int, slug: str, workspace: Path,
                 redact: Redactor) -> tuple[list[str], pi.SessionStats | None]:
    """Redact and upload what the session left. Returns the stored names and the session's
    statistics."""
    prefix = product_prefix(run_id, slug)
    stored: list[str] = []
    stats = None
    own = workspace / RUNNER

    def put(name: str, data: bytes) -> None:
        deps.store.put(prefix + name, data, CONTENT_TYPES[name])
        stored.append(name)

    transcript = _transcript(deps, workspace)
    data = untrusted.read(workspace, transcript, deps.agent.uid, MAX_TRANSCRIPT) if transcript else None
    if data is not None:
        redacted = own / "session.redacted.jsonl"
        redacted.write_bytes(redact.bytes(data))
        put("session.jsonl", redacted.read_bytes())
        stats = pi.session_stats(redacted)
        try:
            pi.export_html(redacted, own / "session.html", pi=deps.pi)
            put("session.html", (own / "session.html").read_bytes())
        except (OSError, subprocess.SubprocessError):
            log.exception("could not render %s's transcript", slug)
    if (own / "stdout.txt").exists():
        put("stdout.txt", redact.bytes((own / "stdout.txt").read_bytes()))
    for name in RESULT_FILES:
        data = untrusted.read(workspace, f"out/{slug}/{name}", deps.agent.uid, MAX_FILE)
        if data is not None:
            put(name, redact.bytes(data))
    return stored, stats


def _publish(settings: Settings, app: App, clone: Clone, accepted: Accepted,
             identity: tuple[str, str], redact: Redactor) -> dict:
    """Push the accepted proposal and open its pull request, with a writing token that only the
    service ever holds (D4). A secret the session could see stays out of the public description."""
    proposal = replace(accepted.proposal, title=redact(accepted.proposal.title),
                       body=redact(accepted.proposal.body))
    try:
        token = app.mint(READ_WRITE).value
        redact.add_token(token)
        clone.publish(proposal, accepted.base, identity, token, settings.repo_url)
        url = app.open_pull_request(token, proposal.branch, proposal.title, proposal.body,
                                    proposal.draft)
    except Exception as exc:
        log.exception("could not publish %s", proposal.slug)
        return {"outcome": "failed", "error": redact(f"publishing the pull request failed: {exc}")}
    return {"outcome": "opened", "pr_url": url}


def execute_product(deps: Deps, settings: Settings, run: Run, slug: str, app: App,
                    redact: Redactor, identity: tuple[str, str]) -> None:
    with deps.Session.begin() as session:
        row = ProductResult(run_id=run.id, slug=slug)
        session.add(row)
    workspace = Path(tempfile.mkdtemp(prefix=f"{slug}-", dir=deps.workdir))
    tokens = TokenFile(app, deps.state_dir / "tokens" / slug, READ_ONLY,
                       on_mint=redact.add_token, share=deps.agent.share)
    fields: dict = {}
    started = False
    try:
        try:
            _prepare(deps, settings, workspace)
            clone = Clone(workspace / RUNNER / CLONE, deps.git,
                          {**os.environ, "GIT_CONFIG_SYSTEM": str(deps.git_config)})
            _update(deps, row.id, commit=_clone(deps, settings, clone.path))
            _agent_clone(deps, settings, workspace)
            tokens.refresh()
            env = session_env(deps, settings, slug, workspace, tokens.path, workspace / "agent",
                              url=run_url(settings, run.id, slug))
            started = True
            deps.live.start(LiveSession(row.id, workspace, redact, deps.agent.uid))
            try:
                ended, verdict = _run_session(deps, settings, workspace, env, tokens, slug, clone)
            finally:
                deps.live.stop(row.id)
        except Exception as exc:
            log.exception("product %s failed before its session ended", slug)
            fields = {"outcome": "failed", "error": redact(f"{exc}")}
            ended, verdict = "", None
        files, stats = _store_files(deps, run.id, slug, workspace, redact) if started else ([], None)
        if ended == "timed_out":
            fields = {"outcome": "timed_out",
                      "error": f"no result after {settings.product_timeout_minutes} minutes"}
        elif ended == "canceled":
            fields = {"outcome": "canceled", "error": "the run was canceled"}
        elif isinstance(verdict, ResultError):
            fields = {"outcome": "failed", "error": redact(str(verdict))}
        elif isinstance(verdict, Accepted):
            doc = verdict.doc
            fields = {
                "outcome": doc["status"],
                "current_version": doc.get("current_version"),
                "target_version": doc.get("target_version"),
                "draft": doc.get("draft"),
                "branch": doc.get("branch"),
                "skip_reason": redact(doc.get("skip_reason")),
                "needs_human": [redact(item) for item in doc.get("needs_human") or []],
                "error": redact(doc.get("error")),
            }
            if verdict.proposal and not settings.dry_run:
                fields.update(_publish(settings, app, clone, verdict, identity, redact))
        if stats:
            fields.update(input_tokens=stats.input_tokens, output_tokens=stats.output_tokens,
                          peak_context=stats.peak_context)
        fields["files"] = files
    except Exception as exc:
        log.exception("could not record product %s", slug)
        fields = {"outcome": "failed", "error": redact(f"recording the result failed: {exc}")}
    finally:
        tokens.remove()
        deps.agent.clean(workspace)
        shutil.rmtree(workspace, ignore_errors=True)
        _update(deps, row.id, finished_at=now(), **fields)


def _discover(deps: Deps, settings: Settings) -> list[str] | None:
    try:
        return fetch(settings.repo_url, git=deps.git, workdir=deps.workdir)
    except Exception:
        log.exception("could not read the catalog from master")
        return None


def _record_failed(deps: Deps, run: Run, slug: str, error: str) -> None:
    stamp = now()
    with deps.Session.begin() as session:
        session.add(ProductResult(run_id=run.id, slug=slug, outcome="failed", error=error,
                                  started_at=stamp, finished_at=stamp))


def _configure_git(deps: Deps, app: App) -> tuple[str, str]:
    name, email = app.identity()
    _git(deps, "config", "--file", str(deps.git_config), "user.name", name)
    _git(deps, "config", "--file", str(deps.git_config), "user.email", email)
    return name, email


def execute_run(deps: Deps, trigger: str, scope: str | None) -> int:
    settings = deps.settings()
    with deps.Session.begin() as session:
        run = Run(trigger=trigger, scope=scope, dry_run=settings.dry_run, pi_version=pi.version(deps.pi),
                  model=settings.inference_model, thinking_level=settings.thinking_level)
        session.add(run)
    deps.cancel.start(run.id)
    try:
        catalog = _discover(deps, settings)
        targets = [scope] if scope else (catalog or [])
        problems = settings.problems()
        app = identity = None
        redact = Redactor(settings.secret_values(), settings.github_app_private_key)
        if not problems:
            try:
                app = deps.github(settings)
                identity = _configure_git(deps, app)
            except Exception as exc:
                log.exception("could not set up GitHub access")
                problems = [redact(f"setting up GitHub access failed: {exc}")]
        for slug in targets:
            if deps.cancel.asked():
                break
            if catalog is not None and slug not in catalog:
                _record_failed(deps, run, slug, f"{slug} is not an eligible product on master")
            elif problems:
                _record_failed(deps, run, slug, "; ".join(problems))
            else:
                execute_product(deps, settings, run, slug, app, redact, identity)
    finally:
        canceled = deps.cancel.stop()
        with deps.Session.begin() as session:
            stored = session.get(Run, run.id)
            stored.state = "canceled" if canceled else "completed"
            stored.finished_at = now()
    with deps.Session() as session:
        notify.send(session.get(Run, run.id), settings, smtp=deps.smtp)
    return run.id
