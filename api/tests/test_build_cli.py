"""`caelus build` CLI tests.

The CLI is a thin shell over `services/builds.py`, so these check the shell:
that it scopes to the acting user, that `submit` performs all three upload
phases in order, and that it reports the resulting image. The object store and
the build worker are both faked — the worker's own behavior is covered in
test_build_worker.py.
"""

from __future__ import annotations

import io
import tarfile
from uuid import UUID

import pytest
from sqlmodel import Session, select

from app.models import BuildORM, UserORM
from app.db import get_engine
from app.services.build_constants import (
    BUILD_STATUS_FAILED,
    BUILD_STATUS_QUEUED,
    BUILD_STATUS_RUNNING,
    BUILD_STATUS_SUCCEEDED,
)
from tests.conftest import cli_runner, make_bare_deployment  # noqa: F401

IMAGE = "1@sha256:" + "e" * 64
CLI_EMAIL = "cli-test@example.com"


def _stdout(result) -> str:
    return getattr(result, "stdout", result.output)


def _project(tmp_path):
    """A minimal project tree, with junk that must not be archived."""
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "package.json").write_text('{"name":"x","scripts":{"start":"node ."}}')
    (root / "src" / "index.js").write_text("console.log(1)")
    (root / "node_modules" / "left-pad").mkdir(parents=True)
    (root / "node_modules" / "left-pad" / "index.js").write_text("// huge")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("[core]")
    return root


@pytest.fixture
def acting_user(cli_runner):
    """The user the CLI acts as, created the way the CLI would create it."""

    with Session(get_engine()) as session:
        user = UserORM(email=CLI_EMAIL)
        session.add(user)
        session.commit()
        session.refresh(user)
        return user.id


def _deployment(user_id: int):
    with Session(get_engine()) as session:
        return make_bare_deployment(session, user_id).id


@pytest.fixture
def acting_deployment(acting_user):
    """The acting user's deployment, which the build commands are scoped by."""
    return _deployment(acting_user)


def _seed_build(user_id: int, deployment_id=None, **kwargs) -> BuildORM:
    deployment_id = deployment_id or _deployment(user_id)
    with Session(get_engine()) as session:
        build = BuildORM(
            deployment_id=deployment_id, artifact_id=kwargs.pop("artifact_id", "a" * 32), **kwargs
        )
        session.add(build)
        session.commit()
        session.refresh(build)
        return build


# ---------------------------------------------------------------------------
# list / show / log
# ---------------------------------------------------------------------------


def test_build_list_returns_the_deployments_builds(cli_runner, acting_user, acting_deployment):
    runner, app = cli_runner
    mine = _seed_build(acting_user, acting_deployment, artifact_id="a" * 32)

    result = runner.invoke(app, ["build", "list", str(acting_user), str(acting_deployment)])

    assert result.exit_code == 0, _stdout(result)
    assert str(mine.id) in _stdout(result)


def test_build_list_excludes_other_deployments_builds(cli_runner, acting_user, acting_deployment):

    runner, app = cli_runner
    with Session(get_engine()) as session:
        other = UserORM(email="someone-else@example.com")
        session.add(other)
        session.commit()
        session.refresh(other)
        other_id = other.id
    theirs = _seed_build(other_id, artifact_id="b" * 32)
    my_other = _seed_build(acting_user, artifact_id="d" * 32)
    mine = _seed_build(acting_user, acting_deployment, artifact_id="c" * 32)

    result = runner.invoke(app, ["build", "list", str(acting_user), str(acting_deployment)])

    assert str(mine.id) in _stdout(result)
    assert str(theirs.id) not in _stdout(result)
    assert str(my_other.id) not in _stdout(result)


def test_build_list_refuses_another_users_account(cli_runner, acting_user):
    runner, app = cli_runner
    with Session(get_engine()) as session:
        other = UserORM(email="someone-else@example.com")
        session.add(other)
        session.commit()
        session.refresh(other)
        other_id = other.id

    result = runner.invoke(app, ["build", "list", str(other_id), str(_deployment(other_id))])

    assert result.exit_code == 1
    assert "admin" in result.output.lower()


def test_build_show_reports_status_and_image(cli_runner, acting_user, acting_deployment):
    runner, app = cli_runner
    build = _seed_build(acting_user, acting_deployment, status=BUILD_STATUS_SUCCEEDED, image=IMAGE)

    result = runner.invoke(
        app, ["build", "show", str(acting_user), str(acting_deployment), str(build.id)]
    )

    assert result.exit_code == 0, _stdout(result)
    assert BUILD_STATUS_SUCCEEDED in _stdout(result)
    assert IMAGE in _stdout(result)


def test_build_show_does_not_find_another_users_build(cli_runner, acting_user, acting_deployment):

    runner, app = cli_runner
    with Session(get_engine()) as session:
        other = UserORM(email="nope@example.com")
        session.add(other)
        session.commit()
        session.refresh(other)
        other_id = other.id
    build = _seed_build(other_id)

    # Under the acting user's own deployment, another owner's build is simply absent.
    result = runner.invoke(
        app, ["build", "show", str(acting_user), str(acting_deployment), str(build.id)]
    )

    assert result.exit_code == 1
    assert "not found" in result.output.lower() or "not found" in _stdout(result).lower()


def test_build_log_prints_the_stored_output(cli_runner, acting_user, acting_deployment):
    runner, app = cli_runner
    build = _seed_build(
        acting_user, acting_deployment, status=BUILD_STATUS_SUCCEEDED, image=IMAGE, log=b"step 1\nstep 2\n"
    )

    result = runner.invoke(
        app, ["build", "log", str(acting_user), str(acting_deployment), str(build.id)]
    )

    assert result.exit_code == 0, _stdout(result)
    assert "step 1" in _stdout(result)
    assert "step 2" in _stdout(result)


def test_build_log_of_an_unknown_build_fails_cleanly(cli_runner, acting_user, acting_deployment):
    runner, app = cli_runner

    result = runner.invoke(
        app,
        ["build", "log", str(acting_user), str(acting_deployment), "00000000-0000-4000-8000-000000000000"],
    )

    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# submit
# ---------------------------------------------------------------------------


class _FakeUpload:
    """Captures the three phases so their order and inputs can be asserted."""

    def __init__(self, monkeypatch, *, status_code: int = 204):
        import app.cli as cli
        from app.services import artifacts as artifact_service

        self.calls: list[str] = []
        self.archive: bytes | None = None
        self.artifact_id = "f" * 32
        self.status_code = status_code

        def _mint(user_id, *, settings=None):
            self.calls.append("mint")
            return artifact_service.ArtifactUploadSlot(
                artifact_id=self.artifact_id,
                url="https://store.invalid/bucket",
                fields={"key": f"artifacts/{user_id}/{self.artifact_id}.tgz", "policy": "x"},
                max_bytes=100 * 1024 * 1024,
                expires_in=900,
            )

        def _post(url, data=None, files=None, timeout=None):
            self.calls.append("upload")
            self.archive = files["file"][1]

            class _Resp:
                status_code = self.status_code
                text = "rejected"

            return _Resp()

        def _exists(user_id, artifact_id, *, settings=None):
            self.calls.append("exists")
            return True

        monkeypatch.setattr(artifact_service, "mint_upload_slot", _mint)
        monkeypatch.setattr("app.services.builds.artifact_exists", _exists)
        import httpx

        monkeypatch.setattr(httpx, "post", _post)


@pytest.fixture
def fake_upload(monkeypatch):
    return _FakeUpload(monkeypatch)


def test_submit_performs_all_three_phases_in_order(cli_runner, acting_user, acting_deployment, fake_upload, tmp_path):
    runner, app = cli_runner
    project = _project(tmp_path)

    result = runner.invoke(app, ["build", "submit", str(acting_deployment), str(project), "--no-wait"])

    assert result.exit_code == 0, _stdout(result)
    # mint -> upload -> (create, which checks the artifact exists)
    assert fake_upload.calls == ["mint", "upload", "exists"]


def test_submit_creates_a_queued_build_for_the_uploaded_artifact(
    cli_runner, acting_user, acting_deployment, fake_upload, tmp_path
):

    runner, app = cli_runner
    project = _project(tmp_path)

    result = runner.invoke(app, ["build", "submit", str(acting_deployment), str(project), "--no-wait"])

    assert result.exit_code == 0, _stdout(result)
    with Session(get_engine()) as session:
        build = session.exec(select(BuildORM)).one()
    assert build.artifact_id == fake_upload.artifact_id
    assert build.deployment_id == acting_deployment
    assert build.status == BUILD_STATUS_QUEUED


def test_submit_archives_the_source_but_not_the_junk(
    cli_runner, acting_user, acting_deployment, fake_upload, tmp_path
):
    """node_modules and .git are never source, and would waste the cap."""
    runner, app = cli_runner
    project = _project(tmp_path)

    runner.invoke(app, ["build", "submit", str(acting_deployment), str(project), "--no-wait"])

    with tarfile.open(fileobj=io.BytesIO(fake_upload.archive), mode="r:gz") as tar:
        names = set(tar.getnames())
    assert "package.json" in names
    assert "src/index.js" in names
    assert not [n for n in names if "node_modules" in n]
    assert not [n for n in names if n.startswith(".git")]


def test_submit_rejects_a_non_directory(cli_runner, acting_user, acting_deployment, fake_upload, tmp_path):
    runner, app = cli_runner
    lonely = tmp_path / "file.txt"
    lonely.write_text("hi")

    result = runner.invoke(app, ["build", "submit", str(acting_deployment), str(lonely), "--no-wait"])

    assert result.exit_code == 1
    assert fake_upload.calls == []


def test_submit_refuses_an_archive_over_the_cap(cli_runner, acting_user, acting_deployment, monkeypatch, tmp_path):
    """Caught locally so the upload is not spent to be told."""
    import app.cli as cli

    runner, app = cli_runner
    project = _project(tmp_path)
    settings = cli.get_settings()
    monkeypatch.setattr(
        cli, "get_settings", lambda: settings.model_copy(update={"artifact_max_bytes": 10})
    )

    result = runner.invoke(app, ["build", "submit", str(acting_deployment), str(project), "--no-wait"])

    assert result.exit_code == 1
    assert "limit" in result.output.lower() or "limit" in _stdout(result).lower()


def test_submit_fails_when_the_store_rejects_the_upload(
    cli_runner, acting_user, acting_deployment, monkeypatch, tmp_path
):
    runner, app = cli_runner
    upload = _FakeUpload(monkeypatch, status_code=400)
    project = _project(tmp_path)

    result = runner.invoke(app, ["build", "submit", str(acting_deployment), str(project), "--no-wait"])

    assert result.exit_code == 1
    assert upload.calls == ["mint", "upload"]  # never reached build creation


def test_submit_reports_the_resulting_image_on_success(
    cli_runner, acting_user, acting_deployment, fake_upload, monkeypatch, tmp_path
):
    """The whole point of --wait: the last line is the value you paste into a
    deployment's `image` user value."""
    import app.cli as cli

    runner, app = cli_runner
    project = _project(tmp_path)

    # Stand in for the build worker: the first poll finds the build finished.
    real_sleep = cli.time.sleep

    def _advance(_seconds):
        with Session(get_engine()) as session:
            build = session.exec(select(BuildORM)).one()
            if build.status == BUILD_STATUS_QUEUED:
                build.status = BUILD_STATUS_SUCCEEDED
                build.image = IMAGE
                build.log = b"built ok\n"
                session.add(build)
                session.commit()
        real_sleep(0)

    monkeypatch.setattr(cli.time, "sleep", _advance)

    result = runner.invoke(app, ["build", "submit", str(acting_deployment), str(project)])

    assert result.exit_code == 0, _stdout(result)
    assert _stdout(result).strip().splitlines()[-1] == IMAGE


def test_submit_exits_non_zero_when_the_build_fails(
    cli_runner, acting_user, acting_deployment, fake_upload, monkeypatch, tmp_path
):
    import app.cli as cli

    runner, app = cli_runner
    project = _project(tmp_path)
    real_sleep = cli.time.sleep

    def _advance(_seconds):
        with Session(get_engine()) as session:
            build = session.exec(select(BuildORM)).one()
            if build.status == BUILD_STATUS_QUEUED:
                build.status = BUILD_STATUS_FAILED
                build.log = b"ERROR: stack detection failed\n"
                session.add(build)
                session.commit()
        real_sleep(0)

    monkeypatch.setattr(cli.time, "sleep", _advance)

    result = runner.invoke(app, ["build", "submit", str(acting_deployment), str(project)])

    assert result.exit_code == 1
    assert IMAGE not in _stdout(result)


def test_submit_without_wait_does_not_block_on_the_worker(
    cli_runner, acting_user, acting_deployment, fake_upload, tmp_path
):
    runner, app = cli_runner
    project = _project(tmp_path)

    result = runner.invoke(app, ["build", "submit", str(acting_deployment), str(project), "--no-wait"])

    assert result.exit_code == 0, _stdout(result)
    assert BUILD_STATUS_QUEUED in _stdout(result)


# ---------------------------------------------------------------------------
# REST / CLI parity
# ---------------------------------------------------------------------------


def test_the_cli_covers_every_build_endpoint(cli_runner):
    """AGENTS.md: CLI and REST stay in lockstep."""
    runner, app = cli_runner

    listing = _stdout(runner.invoke(app, ["build", "--help"]))

    for command in ("list", "show", "log", "submit"):
        assert command in listing
