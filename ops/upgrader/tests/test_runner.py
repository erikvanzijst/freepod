"""Runs and products against a local origin, a fake pi, a fake GitHub and an in-memory bucket."""

import base64
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select

from upgrader import db, runner
from upgrader.config import Settings
from upgrader.github import App

from .fakes import FakeGitHub, MemoryStore
from .test_config import FULL

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
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
        assert [p.slug for p in run.products] == ["immich", "nextcloud", "vaultwarden"]
        assert {p.outcome for p in run.products} == {"up_to_date"}
        assert (run.state, run.trigger, run.dry_run, run.pi_version) == ("completed", "scheduled", True, "0.85.1")
        assert all(p.commit and len(p.commit) == 40 for p in run.products)
    assert list(deps.workdir.iterdir()) == []


def test_would_open_stores_every_file_and_redacts(deps, monkeypatch, github):
    monkeypatch.setenv("FAKE_PI", "result:would_open")
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


def test_the_session_environment(deps, monkeypatch, tmp_path):
    deps.env["DASHBOARD_URL"] = "https://upgrader.test/"
    monkeypatch.setenv("FAKE_PI", "result:up_to_date")
    monkeypatch.setenv("FAKE_PI_ENV", str(tmp_path / "env.json"))
    run_id = runner.execute_run(deps, "manual", "immich")
    env = json.loads((tmp_path / "env.json").read_text())
    assert env["UPGRADE_PRODUCT"] == "immich"
    assert env["UPGRADE_DRY_RUN"] == "1"
    assert env["UPGRADE_RUN_URL"] == f"https://upgrader.test/runs/{run_id}#immich"
    assert env["UPGRADE_OUT_DIR"].startswith(str(deps.workdir))
    assert env["PATH"].split(os.pathsep)[0] == str(runner.HERE / "bin")
    assert env["PI_CODING_AGENT_DIR"] == str(deps.state_dir / "pi-agent")
    assert env["INFERENCE_API_KEY"] == "sk-inference-secret"
    for private in ("GITHUB_APP_PRIVATE_KEY", "DATABASE_URL", "AWS_SECRET_ACCESS_KEY", "GH_TOKEN"):
        assert private not in env
    assert KEY_B64 not in json.dumps(env)


def test_a_deployment_with_no_public_url_names_no_run(deps, monkeypatch, tmp_path):
    """The description then carries no link, rather than one nobody can open."""
    monkeypatch.setenv("FAKE_PI", "result:up_to_date")
    monkeypatch.setenv("FAKE_PI_ENV", str(tmp_path / "env.json"))
    runner.execute_run(deps, "manual", "immich")
    assert json.loads((tmp_path / "env.json").read_text())["UPGRADE_RUN_URL"] == ""


def test_a_real_run_records_every_field_redacted(deps, monkeypatch, github):
    deps.env["UPGRADE_DRY_RUN"] = "0"
    monkeypatch.setenv("FAKE_PI", "result:opened")
    runner.execute_run(deps, "manual", "vaultwarden")
    run, [p] = only_product(deps.Session)
    assert run.dry_run is False
    assert p.outcome == "opened"
    assert p.pr_url == "https://github.com/erikvanzijst/freepod/pull/200"
    assert (p.current_version, p.target_version, p.branch, p.draft) == ("1.37.1", "1.37.3", "upgrade/vaultwarden-1.37.3", True)
    assert p.needs_human == ["Check the invite fix"]
    assert p.error == "CI pending; token [redacted:github-token]"
    assert p.started_at and p.finished_at and p.commit
    assert github.mint_bodies()[0]["permissions"]["contents"] == "write"
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
    _, [p] = only_product(deps.Session)
    assert p.outcome == "failed"
    assert error in p.error
    assert {"session.jsonl", "session.html", "stdout.txt"} <= set(p.files)
    assert list(deps.workdir.iterdir()) == []


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


def test_a_failed_product_does_not_stop_the_run(deps, monkeypatch):
    monkeypatch.setenv("FAKE_PI", "none")
    runner.execute_run(deps, "scheduled", None)
    with deps.Session() as s:
        outcomes = [p.outcome for p in s.scalars(select(db.ProductResult).order_by(db.ProductResult.id))]
    assert outcomes == ["failed", "failed", "failed"]


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
        assert [(p.outcome, p.error) for p in run.products] == [("failed", "INFERENCE_BASE_URL is not set")] * 3


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
