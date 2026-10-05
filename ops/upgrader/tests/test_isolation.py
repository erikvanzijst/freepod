"""The session user, for real: these run only where an `agent` user exists and the service may
become it, as in the image (D1). Elsewhere the service and its sessions share a user, and the
rest of the suite covers the same code paths without the isolation.

The end-to-end test also needs the repository's catalog and a database. From the repo root,
with the devcontainer's Postgres on `src_default`:

    docker build -t upgrader:isolation ops/upgrader
    ctx=$(mktemp -d); mkdir -p $ctx/products $ctx/ops
    cp -r products/catalog products/UPGRADING $ctx/products/
    rsync -a --exclude .venv ops/upgrader $ctx/ops/
    printf 'FROM upgrader:isolation\nUSER root\nRUN uv sync --frozen -q\nCOPY . /repo\n' > $ctx/Dockerfile
    docker build -t upgrader:isolation-test $ctx
    docker run --rm --network src_default \
      -e UPGRADER_TEST_DATABASE_URL=postgresql+psycopg://caelus:caelus@postgres:5432/upgrader_isolation \
      upgrader:isolation-test runuser -u node -- sh -c \
      'cd /repo/ops/upgrader && /app/.venv/bin/python -m pytest -p no:cacheprovider tests/test_isolation.py'
"""

import os
import pwd
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from upgrader import untrusted
from upgrader.agent import Agent

try:
    AGENT = Agent.named()
except KeyError:
    AGENT = None
ISOLATED = AGENT is not None and subprocess.run(
    ["sudo", "-n", "-u", "agent", "true"], capture_output=True).returncode == 0
pytestmark = pytest.mark.skipif(not ISOLATED, reason="needs the image's agent user and sudo rule")
ENV = {"PATH": "/usr/bin:/bin", "HOME": "/home/agent"}


@pytest.fixture
def tmp_path():
    """pytest's own temporary directories are closed to other users."""
    path = Path(tempfile.mkdtemp(prefix="isolation-"))
    path.chmod(0o755)
    yield path
    AGENT.clean(path)
    shutil.rmtree(path, ignore_errors=True)


def as_agent(*argv, **kwargs):
    return AGENT.run(list(argv), env=ENV, capture_output=True, text=True, **kwargs)


def shared(tmp_path):
    directory = tmp_path / "shared"
    directory.mkdir()
    AGENT.share(directory, 0o2770)
    return directory


def test_the_session_user_is_not_the_service():
    assert AGENT.uid != os.getuid()
    assert as_agent("id", "-u").stdout.strip() == str(AGENT.uid)


def test_a_session_cannot_read_the_services_environment():
    out = as_agent("cat", f"/proc/{os.getpid()}/environ")
    assert out.returncode != 0 and out.stdout == ""
    out = as_agent("cat", "/proc/1/environ")
    assert out.returncode != 0 and out.stdout == ""


def test_a_session_cannot_signal_the_service():
    assert as_agent("kill", "-0", str(os.getpid())).returncode != 0


@pytest.mark.parametrize("argv", [["sudo", "-n", "true"], ["sudo", "-n", "-u", pwd.getpwuid(os.getuid()).pw_name, "true"]])
def test_a_session_cannot_escalate(argv):
    assert as_agent(*argv).returncode != 0


def test_the_environment_reaches_the_session_as_given():
    env = {**ENV, "PATH": f"/app/bin:{ENV['PATH']}", "UPGRADE_PRODUCT": "immich"}
    seen = dict(line.split("=", 1) for line in AGENT.run(
        ["env"], env=env, capture_output=True, text=True).stdout.splitlines())
    assert seen["PATH"].split(":")[0] == "/app/bin"
    assert seen["UPGRADE_PRODUCT"] == "immich" and seen["HOME"] == "/home/agent"
    assert "GITHUB_APP_PRIVATE_KEY" not in seen


def test_terminate_ends_processes_that_left_the_group(tmp_path):
    directory = shared(tmp_path)
    pidfile = directory / "escaped"
    process = AGENT.popen(["sh", "-c", f"setsid sleep 600 & echo $! > {pidfile}; sleep 600"], ENV,
                          start_new_session=True)
    deadline = time.monotonic() + 10
    while not pidfile.exists() or not pidfile.read_text().strip():
        assert time.monotonic() < deadline
        time.sleep(0.05)
    AGENT.terminate(process, grace=5)
    assert process.returncode is not None
    left = subprocess.run(["pgrep", "-u", "agent"], capture_output=True, text=True)
    assert left.stdout.strip() == ""


def test_clean_removes_what_the_session_locked(tmp_path):
    directory = shared(tmp_path)
    assert as_agent("sh", "-c", f"mkdir -p {directory}/a/b && touch {directory}/a/b/f && chmod 500 {directory}/a/b {directory}/a").returncode == 0
    AGENT.clean(tmp_path)
    assert list(directory.iterdir()) == []


def test_untrusted_reads_only_what_the_session_owns(tmp_path):
    directory = shared(tmp_path)
    secret = tmp_path / "secret"
    secret.write_text("the-key")
    secret.chmod(0o640)
    assert as_agent("sh", "-c", f"echo ok > {directory}/mine && ln -s {secret} {directory}/link").returncode == 0
    assert untrusted.read(tmp_path, "shared/mine", AGENT.uid, 100) == b"ok\n"
    assert untrusted.read(tmp_path, "shared/link", AGENT.uid, 100) is None
    # The service's own file, even reached plainly, is not the session's.
    (directory / "planted").write_text("x")
    assert untrusted.read(tmp_path, "shared/planted", AGENT.uid, 100) is None


def test_the_token_file_is_readable_to_the_session_alone(tmp_path):
    from upgrader.github import TokenFile

    class App:
        def mint(self, permissions):
            from datetime import UTC, datetime, timedelta

            from upgrader.github import Token
            return Token("ghs_test", datetime.now(UTC) + timedelta(hours=1))

    tokens = TokenFile(App(), tmp_path / "tokens" / "immich", {}, share=AGENT.share)
    tokens.refresh()
    assert as_agent("cat", str(tokens.path)).stdout == "ghs_test"
    assert Path(tokens.path).stat().st_mode & 0o007 == 0


REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.skipif(not (REPO_ROOT / "products" / "UPGRADING").is_dir(), reason="needs the repository's catalog")
def test_a_real_run_through_the_session_user(Session, tmp_path, monkeypatch):
    """The runner end to end as the image runs it: the session as `agent`, the proposal checked
    and published by the service, and nothing of the service's reachable from the session."""
    from sqlalchemy import select

    from upgrader import db, runner
    from upgrader.config import Settings
    from upgrader.github import App

    from .fakes import FakeGitHub, MemoryStore
    from .test_config import FULL
    from .test_runner import GIT, HERE, KEY_B64

    work = tmp_path / "origin-work"
    for rel in ("products/catalog", "products/UPGRADING"):
        shutil.copytree(REPO_ROOT / rel, work / rel)
    git = lambda *a, cwd=work: subprocess.run([GIT, *a], cwd=cwd, check=True, capture_output=True)  # noqa: E731
    git("init", "-q", "-b", "master")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "catalog")
    git("clone", "-q", "--bare", str(work), str(tmp_path / "origin.git"), cwd=tmp_path)
    subprocess.run(["chmod", "-R", "a+rX", str(tmp_path)], check=True)
    for d in ("work", "state"):
        (tmp_path / d).mkdir()
    shared_out = shared(tmp_path)
    fake_pi = tmp_path / "pi"
    shutil.copy(HERE / "fake_pi.py", fake_pi)
    fake_pi.chmod(0o755)

    github = FakeGitHub()
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", KEY_B64)
    monkeypatch.setenv("FAKE_PI", "propose:ok")
    monkeypatch.setenv("FAKE_PI_ENV", str(shared_out / "env.json"))
    env = {**FULL, "GITHUB_APP_PRIVATE_KEY": KEY_B64, "REPO_URL": f"file://{tmp_path / 'origin.git'}",
           "INFERENCE_API_KEY": "sk-inference-secret", "UPGRADE_DRY_RUN": "0"}
    deps = runner.Deps(
        Session=Session, store=MemoryStore(), settings=lambda: Settings.from_env(env),
        github=lambda s: App(s.github_app_id, s.github_app_private_key, http=github.client()),
        pi=str(fake_pi), git=GIT, git_config=tmp_path / "gitconfig", workdir=tmp_path / "work",
        state_dir=tmp_path / "state", poll_seconds=0.05, agent=AGENT,
        extra_env={"FAKE_PI": "propose:ok", "FAKE_PI_ENV": str(shared_out / "env.json"),
                   "FAKE_PI_STAT": str(shared_out / "stat.json")},
    )
    # The stand-in origin is the service's; GitHub, which the image clones from, has no owner.
    (tmp_path / "gitconfig").write_text("[safe]\n\tdirectory = *\n")
    (tmp_path / "gitconfig").chmod(0o644)
    runner.execute_run(deps, "manual", "vaultwarden")
    with Session() as s:
        [p] = s.scalars(select(db.ProductResult)).all()
        assert (p.outcome, p.error) == ("opened", None)
    seen = __import__("json").loads((shared_out / "env.json").read_text())
    assert seen["USER"] == "agent" and seen["HOME"] == "/home/agent"
    assert "GITHUB_APP_PRIVATE_KEY" not in seen
    node, agent = os.getuid(), AGENT.uid
    owners = __import__("json").loads((shared_out / "stat.json").read_text())
    assert owners["."] == [node, AGENT.gid, "0o1770"]
    assert owners["runner"][0] == node and owners["runner"][2] == "0o700"
    assert owners["runner_listed"] is False
    for name in ("agent", "session", "out"):
        assert owners[name] == [node, AGENT.gid, "0o2770"], name
    assert owners["freepod"][0] == agent
    [pull] = github.opened
    assert pull["labels"] == ["product-upgrade"]
    assert list((tmp_path / "work").iterdir()) == []
    assert subprocess.run(["pgrep", "-u", "agent"], capture_output=True).stdout == b""
