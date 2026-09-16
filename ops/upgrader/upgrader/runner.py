"""Executing a run: its products, one at a time, each in a fresh session and clone
(product-upgrade-runs, product-upgrade-history)."""

from __future__ import annotations

import logging
import os
import shutil
import signal
import smtplib
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from . import notify, pi
from .catalog import fetch
from .config import REPO, Settings
from .db import ProductResult, Run, now
from .github import READ_ONLY, READ_WRITE, App, TokenFile
from .live import Live
from .live import Session as LiveSession
from .redact import Redactor
from .result import ResultError, parse_result
from .store import CONTENT_TYPES, product_prefix

log = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parents[1]
PRIVATE_ENV = ("GITHUB_APP_PRIVATE_KEY", "DASHBOARD_PASSWORD", "DATABASE_URL", "BUCKET_NAME",
               "GH_TOKEN", "GITHUB_TOKEN")
PRIVATE_PREFIXES = ("PG", "AWS_", "S3_")
RESULT_FILES = ("result.json", "body.md", "change.patch")


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
    smtp: Callable = smtplib.SMTP
    poll_seconds: float = 15
    extra_env: dict[str, str] = field(default_factory=dict)
    live: Live = field(default_factory=Live)


def _git(deps: Deps, *args: str, cwd: Path | None = None) -> str:
    out = subprocess.run([deps.git, *args], cwd=cwd, capture_output=True, text=True, timeout=600)
    if out.returncode:
        raise RuntimeError(f"git {args[0]} failed: {out.stderr.strip()[-500:]}")
    return out.stdout.strip()


def _clone(deps: Deps, settings: Settings, into: Path) -> str:
    _git(deps, "clone", "-q", "--depth", "1", "--branch", "master", settings.repo_url, str(into))
    return _git(deps, "rev-parse", "HEAD", cwd=into)


def _update(deps: Deps, row_id: int, **values) -> None:
    with deps.Session.begin() as session:
        row = session.get(ProductResult, row_id)
        for key, value in values.items():
            setattr(row, key, value)


def session_env(deps: Deps, settings: Settings, slug: str, workspace: Path, token_file: Path,
                agent_dir: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if k not in PRIVATE_ENV and not k.startswith(PRIVATE_PREFIXES)}
    env.update(deps.extra_env)
    env.update(
        PATH=f"{deps.guards}{os.pathsep}{os.environ.get('PATH', os.defpath)}",
        PI_CODING_AGENT_DIR=str(agent_dir),
        PI_TELEMETRY="0",
        INFERENCE_API_KEY=settings.inference_api_key or "",
        UPGRADE_PRODUCT=slug,
        UPGRADE_DRY_RUN="1" if settings.dry_run else "0",
        UPGRADE_OUT_DIR=str(workspace / "out"),
        UPGRADER_TOKEN_FILE=str(token_file),
        GH_REPO=REPO,
        GIT_CONFIG_SYSTEM=str(deps.git_config),
    )
    return env


def _terminate(process: subprocess.Popen) -> None:
    """End the session's whole process group: pi and everything it spawned (D12)."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        process.poll()
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.2)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def _run_session(deps: Deps, settings: Settings, workspace: Path, env: dict[str, str],
                 tokens: TokenFile, slug: str) -> bool:
    """Run pi until it exits or times out. True when it timed out."""
    clone = workspace / "freepod"
    cmd = pi.command(settings, clone / "products" / "UPGRADING" / "SKILL.md", workspace / "session",
                     slug, pi=deps.pi)
    deadline = time.monotonic() + settings.timeout_seconds
    with (workspace / "stdout.txt").open("wb") as stdout:
        process = subprocess.Popen(cmd, cwd=workspace, env=env, stdin=subprocess.DEVNULL,
                                   stdout=stdout, stderr=subprocess.STDOUT, start_new_session=True)
        timed_out = False
        try:
            while True:
                try:
                    process.wait(timeout=max(0.01, min(deps.poll_seconds, deadline - time.monotonic())))
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() >= deadline:
                        timed_out = True
                        break
                    try:
                        tokens.refresh()
                    except Exception:
                        log.exception("could not refresh the installation token for %s", slug)
        finally:
            _terminate(process)
    return timed_out


def _store_files(deps: Deps, run_id: int, slug: str, workspace: Path,
                 redact: Redactor) -> tuple[list[str], pi.SessionStats | None, bytes | None]:
    """Redact and upload what the session left. Returns the stored names, the session's
    statistics, and the redacted result.json."""
    prefix = product_prefix(run_id, slug)
    stored: list[str] = []
    stats = None

    def put(name: str, data: bytes) -> None:
        deps.store.put(prefix + name, data, CONTENT_TYPES[name])
        stored.append(name)

    transcript = next(iter(sorted((workspace / "session").rglob("*.jsonl"))), None)
    if transcript:
        redacted = workspace / "session.redacted.jsonl"
        redacted.write_bytes(redact.bytes(transcript.read_bytes()))
        put("session.jsonl", redacted.read_bytes())
        stats = pi.session_stats(redacted)
        try:
            pi.export_html(redacted, workspace / "session.html", pi=deps.pi)
            put("session.html", (workspace / "session.html").read_bytes())
        except (OSError, subprocess.SubprocessError):
            log.exception("could not render %s's transcript", slug)
    if (workspace / "stdout.txt").exists():
        put("stdout.txt", redact.bytes((workspace / "stdout.txt").read_bytes()))
    result = None
    out = workspace / "out" / slug
    for name in RESULT_FILES:
        if (out / name).is_file():
            data = redact.bytes((out / name).read_bytes())
            put(name, data)
            if name == "result.json":
                result = data
    return stored, stats, result


def execute_product(deps: Deps, settings: Settings, run: Run, slug: str, app: App,
                    redact: Redactor, agent_dir: Path) -> None:
    with deps.Session.begin() as session:
        row = ProductResult(run_id=run.id, slug=slug)
        session.add(row)
    workspace = Path(tempfile.mkdtemp(prefix=f"{slug}-", dir=deps.workdir))
    tokens = TokenFile(app, deps.state_dir / "token", READ_ONLY if settings.dry_run else READ_WRITE,
                       on_mint=redact.add_token)
    fields: dict = {}
    started = False
    try:
        try:
            commit = _clone(deps, settings, workspace / "freepod")
            _update(deps, row.id, commit=commit)
            tokens.refresh()
            env = session_env(deps, settings, slug, workspace, tokens.path, agent_dir)
            started = True
            deps.live.start(LiveSession(row.id, workspace / "session", redact))
            try:
                timed_out = _run_session(deps, settings, workspace, env, tokens, slug)
            finally:
                deps.live.stop(row.id)
        except Exception as exc:
            log.exception("product %s failed before its session ended", slug)
            fields = {"outcome": "failed", "error": redact(f"{exc}")}
            timed_out = False
        files, stats, raw = _store_files(deps, run.id, slug, workspace, redact) if started else ([], None, None)
        if timed_out:
            fields = {"outcome": "timed_out",
                      "error": f"no result after {settings.product_timeout_minutes} minutes"}
        elif not fields:
            try:
                doc = parse_result(raw, workspace / "freepod" / "products" / "UPGRADING" /
                                   "result.schema.json", slug, settings.dry_run)
                fields = {
                    "outcome": doc["status"],
                    "current_version": doc.get("current_version"),
                    "target_version": doc.get("target_version"),
                    "pr_url": doc.get("pr_url"),
                    "draft": doc.get("draft"),
                    "branch": doc.get("branch"),
                    "skip_reason": doc.get("skip_reason"),
                    "needs_human": doc.get("needs_human") or [],
                    "error": doc.get("error"),
                }
            except ResultError as exc:
                fields = {"outcome": "failed", "error": str(exc)}
        if stats:
            fields.update(input_tokens=stats.input_tokens, output_tokens=stats.output_tokens,
                          peak_context=stats.peak_context)
        fields["files"] = files
    except Exception as exc:
        log.exception("could not record product %s", slug)
        fields = {"outcome": "failed", "error": redact(f"recording the result failed: {exc}")}
    finally:
        tokens.remove()
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


def _configure_git(deps: Deps, app: App) -> None:
    name, email = app.identity()
    _git(deps, "config", "--file", str(deps.git_config), "user.name", name)
    _git(deps, "config", "--file", str(deps.git_config), "user.email", email)


def execute_run(deps: Deps, trigger: str, scope: str | None) -> int:
    settings = deps.settings()
    with deps.Session.begin() as session:
        run = Run(trigger=trigger, scope=scope, dry_run=settings.dry_run, pi_version=pi.version(deps.pi),
                  model=settings.inference_model, thinking_level=settings.thinking_level)
        session.add(run)
    try:
        catalog = _discover(deps, settings)
        targets = [scope] if scope else (catalog or [])
        problems = settings.problems()
        app = None
        redact = Redactor(settings.secret_values(), settings.github_app_private_key)
        if not problems:
            try:
                app = deps.github(settings)
                _configure_git(deps, app)
            except Exception as exc:
                log.exception("could not set up GitHub access")
                problems = [redact(f"setting up GitHub access failed: {exc}")]
        agent_dir = pi.write_agent_dir(deps.state_dir / "pi-agent", settings) if not problems else None
        for slug in targets:
            if catalog is not None and slug not in catalog:
                _record_failed(deps, run, slug, f"{slug} is not an eligible product on master")
            elif problems:
                _record_failed(deps, run, slug, "; ".join(problems))
            else:
                execute_product(deps, settings, run, slug, app, redact, agent_dir)
    finally:
        with deps.Session.begin() as session:
            stored = session.get(Run, run.id)
            stored.state, stored.finished_at = "completed", now()
    with deps.Session() as session:
        notify.send(session.get(Run, run.id), settings, smtp=deps.smtp)
    return run.id
