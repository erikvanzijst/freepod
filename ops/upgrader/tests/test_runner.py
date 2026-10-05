"""Runs and products against a local origin, a fake pi, a fake GitHub and an in-memory bucket."""

import base64
import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select

from upgrader import db, runner
from upgrader.agent import Agent
from upgrader.catalog import eligible
from upgrader.config import Settings
from upgrader.github import App

from .fakes import FakeGitHub, MemoryStore
from .test_config import FULL

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
ELIGIBLE = eligible(REPO_ROOT)
GIT = shutil.which("git", path="/usr/local/bin:/usr/bin")
KEY_B64 = base64.b64encode(
    rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
).decode()


@pytest.fixture(scope="module")
def origin(tmp_path_factory):
    """A bare repository with the real catalog and result contract on master."""
    base = tmp_path_factory.mktemp("origin")
    work = base / "work"
    for rel in ("products/catalog", "products/UPGRADING"):
        shutil.copytree(REPO_ROOT / rel, work / rel)
    git = lambda *a, cwd=work: subprocess.run([GIT, *a], cwd=cwd, check=True, capture_output=True)  # noqa: E731
    git("init", "-q", "-b", "master")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "catalog")
    git("clone", "-q", "--bare", str(work), str(base / "origin.git"), cwd=base)
    return f"file://{base / 'origin.git'}"


@pytest.fixture
def github():
    return FakeGitHub()


@pytest.fixture
def deps(Session, origin, github, tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", KEY_B64)
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret-db")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s3-secret")
    env = {**FULL, "GITHUB_APP_PRIVATE_KEY": KEY_B64, "REPO_URL": origin,
           "INFERENCE_API_KEY": "sk-inference-secret", "PRODUCT_TIMEOUT_MINUTES": "1"}
    fake_pi = tmp_path / "pi"
    fake_pi.symlink_to(HERE / "fake_pi.py")
    (tmp_path / "work").mkdir()
    d = runner.Deps(
        Session=Session,
        store=MemoryStore(),
        settings=lambda: Settings.from_env(env),
        github=lambda s: App(s.github_app_id, s.github_app_private_key, http=github.client()),
        pi=str(fake_pi),
        git=GIT,
        git_config=tmp_path / "gitconfig",
        workdir=tmp_path / "work",
        state_dir=tmp_path / "state",
        poll_seconds=0.05,
        agent=Agent.same_user(),
    )
    d.env = env
    return d


def only_product(Session):
    with Session() as s:
        run = s.scalars(select(db.Run)).one()
        return run, run.products


def objects(deps, slug):
    return {k.rsplit("/", 1)[1] for k in deps.store.objects if f"/{slug}/" in k}


def test_a_catalog_run_covers_the_eligible_products_in_order(deps, monkeypatch):
    monkeypatch.setenv("FAKE_PI", "result:up_to_date")
    run_id = runner.execute_run(deps, "scheduled", None)
    with deps.Session() as s:
        run = s.get(db.Run, run_id)
        assert [p.slug for p in run.products] == ELIGIBLE
        assert {p.outcome for p in run.products} == {"up_to_date"}
        assert (run.state, run.trigger, run.dry_run, run.pi_version) == ("completed", "scheduled", True, "0.85.1")
        assert all(p.commit and len(p.commit) == 40 for p in run.products)
    assert list(deps.workdir.iterdir()) == []


def test_would_open_stores_every_file_and_redacts(deps, monkeypatch, github):
    monkeypatch.setenv("FAKE_PI", "propose:ok")
    runner.execute_run(deps, "manual", "vaultwarden")
    run, [p] = only_product(deps.Session)
    assert (p.outcome, p.target_version, p.branch, p.draft) == ("would_open", "1.37.3", "upgrade/vaultwarden-1.37.3", True)
    assert p.needs_human == ["Check the invite fix"]
    assert (p.input_tokens, p.output_tokens, p.peak_context) == (1000, 200, 1500)
    assert set(p.files) == objects(deps, "vaultwarden") == {
        "session.jsonl", "session.html", "stdout.txt", "result.json", "body.md", "change.patch"}
    for key, (data, content_type) in deps.store.objects.items():
        assert key.startswith(f"runs/{run.id}/vaultwarden/")
        assert b"ghs_minted" not in data and b"sk-inference-secret" not in data
    assert b"[redacted:github-token]" in deps.store.objects[f"runs/{run.id}/vaultwarden/session.jsonl"][0]
    assert b"[redacted:INFERENCE_API_KEY]" in deps.store.objects[f"runs/{run.id}/vaultwarden/session.jsonl"][0]
    assert deps.store.objects[f"runs/{run.id}/vaultwarden/session.html"][1].startswith("text/html")
    assert set(github.mint_bodies()[0]["permissions"].values()) == {"read"}
    assert github.opened == [], "a dry run publishes nothing"


def test_the_session_environment(deps, monkeypatch, tmp_path):
    deps.env["DASHBOARD_URL"] = "https://upgrader.test/"
    monkeypatch.setenv("FAKE_PI", "result:up_to_date")
    monkeypatch.setenv("FAKE_PI_ENV", str(tmp_path / "env.json"))
    monkeypatch.setenv("SMTP_PASS", "smtp-secret")
    run_id = runner.execute_run(deps, "manual", "immich")
    env = json.loads((tmp_path / "env.json").read_text())
    assert env["UPGRADE_PRODUCT"] == "immich"
    assert env["UPGRADE_DRY_RUN"] == "1"
    assert env["UPGRADE_RUN_URL"] == f"https://upgrader.test/runs/{run_id}#immich"
    assert env["UPGRADE_OUT_DIR"].startswith(str(deps.workdir))
    assert env["PATH"].split(os.pathsep)[0] == str(runner.HERE / "bin")
    workspace = Path(env["UPGRADE_OUT_DIR"]).parent
    assert env["PI_CODING_AGENT_DIR"] == str(workspace / "agent")
    assert env["UPGRADER_TOKEN_FILE"] == str(deps.state_dir / "tokens" / "immich")
    assert env["HOME"] == deps.agent.home
    assert env["INFERENCE_API_KEY"] == "sk-inference-secret"
    for private in ("GITHUB_APP_PRIVATE_KEY", "SMTP_PASS", "DATABASE_URL", "AWS_SECRET_ACCESS_KEY", "GH_TOKEN"):
        assert private not in env
    assert KEY_B64 not in json.dumps(env)


def test_a_deployment_with_no_public_url_names_no_run(deps, monkeypatch, tmp_path):
    """The description then carries no link, rather than one nobody can open."""
    monkeypatch.setenv("FAKE_PI", "result:up_to_date")
    monkeypatch.setenv("FAKE_PI_ENV", str(tmp_path / "env.json"))
    runner.execute_run(deps, "manual", "immich")
    assert json.loads((tmp_path / "env.json").read_text())["UPGRADE_RUN_URL"] == ""


def git_out(origin, *args):
    return subprocess.run([GIT, *args], cwd=origin.removeprefix("file://"), capture_output=True,
                          text=True).stdout.strip()


def test_a_real_run_publishes_the_proposal(deps, monkeypatch, github, origin):
    deps.env["UPGRADE_DRY_RUN"] = "0"
    monkeypatch.setenv("FAKE_PI", "propose:ok")
    argvs = []

    class Recording(subprocess.Popen):
        def __init__(self, args, *a, **kw):
            argvs.append(" ".join(map(str, args)) if isinstance(args, (list, tuple)) else str(args))
            super().__init__(args, *a, **kw)

    monkeypatch.setattr(subprocess, "Popen", Recording)
    runner.execute_run(deps, "manual", "vaultwarden")
    assert any(" push " in a for a in argvs)
    assert not [a for a in argvs if "ghs_minted" in a], "a token is never on a command line"
    run, [p] = only_product(deps.Session)
    assert run.dry_run is False
    assert (p.outcome, p.error) == ("opened", None)
    assert p.pr_url == "https://github.com/erikvanzijst/freepod/pull/300"
    assert (p.current_version, p.target_version, p.branch, p.draft) == ("1.37.1", "1.37.3", "upgrade/vaultwarden-1.37.3", True)
    assert p.needs_human == ["Check the invite fix"]
    assert p.started_at and p.finished_at and p.commit
    [pull] = github.opened
    assert (pull["head"], pull["base"], pull["draft"], pull["labels"]) == (
        "upgrade/vaultwarden-1.37.3", "master", True, ["product-upgrade"])
    assert pull["title"] == "Vaultwarden: Upgrade to 1.37.3"
    assert "ghs_minted" not in pull["body"] and "[redacted:github-token]" in pull["body"]
    # The sessions' tokens read; only the one the service minted to publish writes.
    perms = [b["permissions"] for b in github.mint_bodies()]
    assert all(set(pm.values()) == {"read"} for pm in perms[:-1])
    assert perms[-1]["contents"] == "write" and pull["token"] == f"token ghs_minted{len(perms)}"
    # The pushed branch is the patch, authored as the bot, whatever the patch said.
    ref = "refs/heads/upgrade/vaultwarden-1.37.3"
    assert git_out(origin, "log", "-1", "--format=%an <%ae>|%cn", ref) == (
        "freepod-upgrader[bot] <4242+freepod-upgrader[bot]@users.noreply.github.com>|freepod-upgrader[bot]")
    assert git_out(origin, "diff", "--name-only", f"master..{ref}") == "products/catalog/vaultwarden.yaml"
    assert git_out(origin, "log", "-1", "--format=%s", ref) == "vaultwarden: Upgrade to 1.37.3"


def test_a_branch_that_already_exists_fails_the_product(deps, monkeypatch, github, origin):
    git_out(origin, "branch", "upgrade/vaultwarden-1.37.3", "master")
    deps.env["UPGRADE_DRY_RUN"] = "0"
    monkeypatch.setenv("FAKE_PI", "propose:ok")
    runner.execute_run(deps, "manual", "vaultwarden")
    _, [p] = only_product(deps.Session)
    assert p.outcome == "failed" and p.pr_url is None
    assert "publishing the pull request failed" in p.error and "push failed" in p.error
    assert github.opened == []
    git_out(origin, "branch", "-D", "upgrade/vaultwarden-1.37.3")


@pytest.mark.parametrize("dry", ["1", "0"])
@pytest.mark.parametrize(
    "kind, reason",
    [
        ("other-product", "changes products/catalog/nextcloud.yaml, outside"),
        ("workflow", "changes .github/workflows/ci.yml, outside"),
        ("link", "links an issue or pull request"),
        ("mention", "has an @ outside backticks"),
        ("symlink-body", "body.md is missing"),
    ],
)
def test_a_refused_proposal_gets_the_repair_turn(deps, monkeypatch, github, origin, tmp_path, dry, kind, reason):
    secret = tmp_path / "service-secret"
    secret.write_text("GITHUB_APP_PRIVATE_KEY=the-key")
    monkeypatch.setenv("FAKE_PI_SECRET", str(secret))
    deps.env["UPGRADE_DRY_RUN"] = dry
    monkeypatch.setenv("FAKE_PI", f"propose:{kind}")
    runner.execute_run(deps, "manual", "vaultwarden")
    run, [p] = only_product(deps.Session)
    stdout = deps.store.objects[f"runs/{run.id}/vaultwarden/stdout.txt"][0].decode()
    first, repair = stdout.split("prompt: ")[1:]
    assert reason in repair
    assert p.outcome == ("would_open" if dry == "1" else "opened"), "the repaired proposal is accepted"
    assert len(github.opened) == (0 if dry == "1" else 1)
    assert git_out(origin, "branch", "--list", "upgrade/*") == ("" if dry == "1" else "upgrade/vaultwarden-1.37.3")
    git_out(origin, "branch", "-D", "upgrade/vaultwarden-1.37.3")
    for data, _ in deps.store.objects.values():
        assert b"the-key" not in data
    assert secret.read_text() == "GITHUB_APP_PRIVATE_KEY=the-key"


def test_a_session_cannot_loosen_the_contract_in_its_clone(deps, monkeypatch):
    monkeypatch.setenv("FAKE_PI", "tampered-schema")
    runner.execute_run(deps, "manual", "immich")
    _, [p] = only_product(deps.Session)
    assert p.outcome == "failed" and "does not follow the contract" in p.error


def test_a_session_never_reports_opened(deps, monkeypatch, github):
    deps.env["UPGRADE_DRY_RUN"] = "0"
    monkeypatch.setenv("FAKE_PI", "opened")
    runner.execute_run(deps, "manual", "immich")
    _, [p] = only_product(deps.Session)
    assert p.outcome == "failed" and p.pr_url is None
    assert github.opened == []


def test_a_workspace_the_session_locked_is_still_deleted(deps, monkeypatch):
    monkeypatch.setenv("FAKE_PI", "unwritable")
    runner.execute_run(deps, "manual", "immich")
    _, [p] = only_product(deps.Session)
    assert p.outcome == "up_to_date"
    assert list(deps.workdir.iterdir()) == []


def test_the_bots_identity_is_configured(deps, monkeypatch):
    monkeypatch.setenv("FAKE_PI", "result:up_to_date")
    runner.execute_run(deps, "manual", "immich")
    name, email = (subprocess.run([GIT, "config", "--file", str(deps.git_config), k], capture_output=True,
                                  text=True).stdout.strip() for k in ("user.name", "user.email"))
    assert (name, email) == ("freepod-upgrader[bot]", "4242+freepod-upgrader[bot]@users.noreply.github.com")


@pytest.mark.parametrize(
    "mode, error",
    [
        ("none", "without writing result.json"),
        ("malformed", "not valid JSON"),
        ("wrong-product", "is for 'nextcloud', not 'immich'"),
        ("dry-mismatch", "dry_run=False"),
    ],
)
def test_a_bad_result_fails_the_product(deps, monkeypatch, mode, error):
    monkeypatch.setenv("FAKE_PI", mode)
    runner.execute_run(deps, "manual", "immich")
    run, [p] = only_product(deps.Session)
    assert p.outcome == "failed"
    assert error in p.error
    stdout = deps.store.objects[f"runs/{run.id}/immich/stdout.txt"][0].decode()
    assert stdout.count("prompt: ") == 2, "one repair turn, and no more"
    assert {"session.jsonl", "session.html", "stdout.txt"} <= set(p.files)
    assert list(deps.workdir.iterdir()) == []


def test_a_bad_result_gets_one_turn_in_the_same_session_to_fix_it(deps, monkeypatch):
    monkeypatch.setenv("FAKE_PI", "repairable")
    runner.execute_run(deps, "manual", "bookstack")
    run, [p] = only_product(deps.Session)
    assert (p.outcome, p.pr_url, p.error) == ("up_to_date", None, None)
    stdout = deps.store.objects[f"runs/{run.id}/bookstack/stdout.txt"][0].decode()
    first, repair = stdout.split("prompt: ")[1:]
    assert "Run the upgrade-product skill" in first
    assert "does not follow the contract at schema_version" in repair and "bookstack/result.json" in repair
    assert (p.input_tokens, p.output_tokens) == (2000, 400), "both turns land in one transcript"


def test_a_timeout_terminates_the_session_and_its_children(deps, monkeypatch, tmp_path):
    deps.settings = lambda: Settings.from_env({**deps.env, "PRODUCT_TIMEOUT_MINUTES": "1"})
    monkeypatch.setattr(Settings, "timeout_seconds", property(lambda self: 2))
    monkeypatch.setenv("FAKE_PI", "sleep")
    monkeypatch.setenv("FAKE_PI_CHILD", str(tmp_path / "child"))
    runner.execute_run(deps, "manual", "nextcloud")
    _, [p] = only_product(deps.Session)
    assert p.outcome == "timed_out"
    assert {"session.jsonl", "session.html", "stdout.txt"} <= set(p.files)
    child = int((tmp_path / "child").read_text())
    state = Path(f"/proc/{child}/stat")
    assert not state.exists() or state.read_text().split(")")[1].split()[0] in ("Z", "X")
    assert list(deps.workdir.iterdir()) == []


def test_canceling_a_run_ends_its_session_and_stops_the_run(deps, monkeypatch, tmp_path):
    """The owner aborts a doomed session: its process group goes with it, and the run's
    remaining products never start."""
    monkeypatch.setenv("FAKE_PI", "sleep")
    monkeypatch.setenv("FAKE_PI_CHILD", str(tmp_path / "child"))
    child_file = tmp_path / "child"
    asked = []

    def abort():
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not child_file.exists():
            time.sleep(0.02)
        with deps.Session() as s:
            run = s.scalars(select(db.Run)).one()
        asked.append(deps.cancel.request(run.id))

    thread = threading.Thread(target=abort)
    thread.start()
    runner.execute_run(deps, "scheduled", None)
    thread.join(10)
    assert asked == [True]
    with deps.Session() as s:
        run = s.scalars(select(db.Run)).one()
        assert run.state == "canceled" and run.finished_at
        # The products after the canceled one never start.
        assert [(p.slug, p.outcome) for p in run.products] == [(ELIGIBLE[0], "canceled")]
        assert run.products[0].error == "the run was canceled"
        assert {"session.jsonl", "stdout.txt"} <= set(run.products[0].files)
    child = int(child_file.read_text())
    state = Path(f"/proc/{child}/stat")
    assert not state.exists() or state.read_text().split(")")[1].split()[0] in ("Z", "X")
    assert list(deps.workdir.iterdir()) == []


def test_a_run_after_a_canceled_one_runs_normally(deps, monkeypatch):
    """The cancel is forgotten with the run it belonged to."""
    monkeypatch.setenv("FAKE_PI", "result:up_to_date")
    deps.cancel.start(-1)
    assert deps.cancel.request(-1) is True
    runner.execute_run(deps, "manual", "immich")
    run, [p] = only_product(deps.Session)
    assert (run.state, p.outcome) == ("completed", "up_to_date")


def test_a_failed_product_does_not_stop_the_run(deps, monkeypatch):
    monkeypatch.setenv("FAKE_PI", "none")
    runner.execute_run(deps, "scheduled", None)
    with deps.Session() as s:
        outcomes = [p.outcome for p in s.scalars(select(db.ProductResult).order_by(db.ProductResult.id))]
    assert outcomes == ["failed"] * len(ELIGIBLE)


def test_one_ineligible_product_is_recorded_failed(deps):
    runner.execute_run(deps, "manual", "custom")
    _, [p] = only_product(deps.Session)
    assert (p.slug, p.outcome) == ("custom", "failed")
    assert "not an eligible product" in p.error


def test_a_missing_required_var_fails_the_runs_products(deps):
    deps.settings = lambda: Settings.from_env({k: v for k, v in deps.env.items() if k != "INFERENCE_BASE_URL"})
    runner.execute_run(deps, "scheduled", None)
    with deps.Session() as s:
        run = s.scalars(select(db.Run)).one()
        assert run.state == "completed"
        assert [(p.outcome, p.error) for p in run.products] == [("failed", "INFERENCE_BASE_URL is not set")] * len(ELIGIBLE)


def test_interrupted_rows_are_closed_at_the_next_start(Session):
    with Session.begin() as s:
        run = db.Run(trigger="scheduled", dry_run=True)
        run.products = [db.ProductResult(slug="immich", outcome="up_to_date", finished_at=db.now()),
                        db.ProductResult(slug="nextcloud")]
        s.add(run)
        done = db.Run(trigger="manual", dry_run=True, state="completed", finished_at=db.now())
        s.add(done)
    db.close_interrupted(Session)
    with Session() as s:
        runs = {r.id: r for r in s.scalars(select(db.Run))}
        assert runs[run.id].state == "interrupted" and runs[run.id].finished_at
        assert [p.outcome for p in runs[run.id].products] == ["up_to_date", "interrupted"]
        assert runs[done.id].state == "completed"


@pytest.mark.skipif(shutil.which("pi") is None, reason="needs the pi binary")
def test_a_real_pi_export_of_a_fixture_transcript_produces_html(tmp_path):
    from upgrader import pi

    pi.export_html(HERE / "fixtures" / "session.jsonl", tmp_path / "session.html")
    html = (tmp_path / "session.html").read_text()
    assert html.lstrip().lower().startswith("<!doctype html") and "</html>" in html
