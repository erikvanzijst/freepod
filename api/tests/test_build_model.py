"""Data model tests for the build record.

Everything here is deliberately service-free: it exercises the ORM, the state
machine, and the database constraints directly, so a later regression in
`services/builds.py` cannot mask a broken invariant here (or vice versa).
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.models import BuildCreate, BuildORM, BuildRead, DeploymentORM
from app.services.build_constants import (
    BUILD_STATUS_CANCELED,
    BUILD_STATUS_FAILED,
    BUILD_STATUS_QUEUED,
    BUILD_STATUS_RUNNING,
    BUILD_STATUS_SUCCEEDED,
    BUILD_STATUSES,
    BUILD_STATUSES_OPEN,
    BUILD_STATUSES_TERMINAL,
    can_transition,
    is_terminal,
)
from tests.conftest import db_session, make_accepted_user, make_bare_deployment  # noqa: F401

IMAGE = "5@sha256:" + "a" * 64


def _user(session, email="build-model@example.com"):
    return make_accepted_user(session, email)


def _deployment_id(session, user_id):
    """The user's deployment, created on first use."""
    existing = session.exec(
        select(DeploymentORM.id).where(DeploymentORM.user_id == user_id)
    ).first()
    return existing or make_bare_deployment(session, user_id).id


def _build(session, user_id, artifact_id, **kwargs) -> BuildORM:
    kwargs.setdefault("deployment_id", _deployment_id(session, user_id))
    build = BuildORM(artifact_id=artifact_id, **kwargs)
    session.add(build)
    session.commit()
    session.refresh(build)
    return build


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


def test_new_build_is_queued_with_no_timestamps_or_image(db_session):
    user = _user(db_session)
    build = _build(db_session, user.id, "artifact-new")

    assert build.status == BUILD_STATUS_QUEUED
    assert build.started_at is None
    assert build.finished_at is None
    assert build.image is None
    assert build.job_id is None
    assert build.log == b""


def test_queued_to_running_records_start(db_session):
    user = _user(db_session)
    build = _build(db_session, user.id, "artifact-start")
    now = datetime.now(UTC)

    build.transition_to(BUILD_STATUS_RUNNING, now=now)

    assert build.status == BUILD_STATUS_RUNNING
    assert build.started_at == now
    assert build.finished_at is None
    assert build.image is None


def test_running_to_succeeded_records_finish_and_image(db_session):
    user = _user(db_session)
    build = _build(db_session, user.id, "artifact-success")
    started = datetime.now(UTC)
    finished = started + timedelta(minutes=3)

    build.transition_to(BUILD_STATUS_RUNNING, now=started)
    build.transition_to(BUILD_STATUS_SUCCEEDED, image=IMAGE, now=finished)

    assert build.status == BUILD_STATUS_SUCCEEDED
    assert build.started_at == started
    assert build.finished_at == finished
    assert build.image == IMAGE


def test_running_to_failed_records_finish_without_image(db_session):
    user = _user(db_session)
    build = _build(db_session, user.id, "artifact-failure")

    build.transition_to(BUILD_STATUS_RUNNING)
    build.transition_to(BUILD_STATUS_FAILED)

    assert build.status == BUILD_STATUS_FAILED
    assert build.finished_at is not None
    assert build.image is None


def test_queued_cannot_skip_straight_to_a_terminal_status(db_session):
    user = _user(db_session)
    build = _build(db_session, user.id, "artifact-skip")

    with pytest.raises(ValueError, match="illegal build transition"):
        build.transition_to(BUILD_STATUS_SUCCEEDED, image=IMAGE)
    with pytest.raises(ValueError, match="illegal build transition"):
        build.transition_to(BUILD_STATUS_FAILED)

    assert build.status == BUILD_STATUS_QUEUED


@pytest.mark.parametrize("terminal", BUILD_STATUSES_TERMINAL)
@pytest.mark.parametrize("target", BUILD_STATUSES)
def test_terminal_states_are_final(db_session, terminal, target):
    """No status, including itself, is reachable from a terminal one."""
    user = _user(db_session)
    build = _build(db_session, user.id, f"artifact-final-{terminal}-{target}", status=terminal)

    with pytest.raises(ValueError, match="illegal build transition"):
        build.transition_to(target, image=IMAGE if target == BUILD_STATUS_SUCCEEDED else None)

    assert build.status == terminal


def test_a_failed_build_cannot_be_requeued(db_session):
    """Recovery is a *new* build; there is no edge back into `queued`."""
    user = _user(db_session)
    build = _build(db_session, user.id, "artifact-requeue")
    build.transition_to(BUILD_STATUS_RUNNING)
    build.transition_to(BUILD_STATUS_FAILED)

    with pytest.raises(ValueError, match="illegal build transition"):
        build.transition_to(BUILD_STATUS_QUEUED)


def test_canceled_is_reserved_and_unreachable(db_session):
    """The state exists in the vocabulary; nothing in this change reaches it."""
    assert BUILD_STATUS_CANCELED in BUILD_STATUSES
    assert is_terminal(BUILD_STATUS_CANCELED)
    for status in BUILD_STATUSES:
        assert not can_transition(status, BUILD_STATUS_CANCELED)


# ---------------------------------------------------------------------------
# `image` is null until succeeded
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [BUILD_STATUS_QUEUED, BUILD_STATUS_RUNNING, BUILD_STATUS_FAILED])
def test_image_is_null_in_every_non_succeeded_status(db_session, status):
    user = _user(db_session)
    build = _build(db_session, user.id, f"artifact-image-{status}")
    if status != BUILD_STATUS_QUEUED:
        build.transition_to(BUILD_STATUS_RUNNING)
    if status == BUILD_STATUS_FAILED:
        build.transition_to(BUILD_STATUS_FAILED)

    assert build.status == status
    assert build.image is None
    assert BuildRead.model_validate(build, from_attributes=True).image is None


def test_succeeding_without_an_image_is_refused(db_session):
    """A success reporting no usable image is a failure, not a success."""
    user = _user(db_session)
    build = _build(db_session, user.id, "artifact-no-image")
    build.transition_to(BUILD_STATUS_RUNNING)

    with pytest.raises(ValueError, match="requires an image"):
        build.transition_to(BUILD_STATUS_SUCCEEDED)

    assert build.status == BUILD_STATUS_RUNNING
    assert build.image is None


def test_image_cannot_be_attached_to_a_failure(db_session):
    user = _user(db_session)
    build = _build(db_session, user.id, "artifact-failed-image")
    build.transition_to(BUILD_STATUS_RUNNING)

    with pytest.raises(ValueError, match="only be set when succeeding"):
        build.transition_to(BUILD_STATUS_FAILED, image=IMAGE)

    assert build.image is None


def test_image_is_a_flat_string_not_a_structured_object(db_session):
    """It is submitted verbatim as a product's `image` user value (D13)."""
    user = _user(db_session)
    build = _build(db_session, user.id, "artifact-flat")
    build.transition_to(BUILD_STATUS_RUNNING)
    build.transition_to(BUILD_STATUS_SUCCEEDED, image=f"{user.id}@sha256:{'b' * 64}")

    read = BuildRead.model_validate(build, from_attributes=True)
    assert isinstance(read.image, str)
    assert read.image == f"{user.id}@sha256:{'b' * 64}"


# ---------------------------------------------------------------------------
# At most one non-terminal build per artifact
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("open_status", BUILD_STATUSES_OPEN)
def test_second_non_terminal_build_for_one_artifact_is_refused(db_session, open_status):
    user = _user(db_session)
    _build(db_session, user.id, "artifact-inflight", status=open_status)

    with pytest.raises(IntegrityError):
        _build(db_session, user.id, "artifact-inflight", status=BUILD_STATUS_QUEUED)
    db_session.rollback()


def test_the_constraint_spans_users(db_session):
    """artifact_id is server-generated and globally unique, so the index needs
    no owner or deployment component — and must not silently gain one."""
    owner = _user(db_session, "artifact-owner@example.com")
    other = _user(db_session, "artifact-other@example.com")
    _build(db_session, owner.id, "artifact-shared", status=BUILD_STATUS_RUNNING)

    with pytest.raises(IntegrityError):
        _build(db_session, other.id, "artifact-shared", status=BUILD_STATUS_QUEUED)
    db_session.rollback()


@pytest.mark.parametrize("terminal", BUILD_STATUSES_TERMINAL)
def test_rebuild_is_allowed_once_the_previous_build_is_terminal(db_session, terminal):
    user = _user(db_session)
    first = _build(db_session, user.id, "artifact-rebuild", status=terminal)

    second = _build(db_session, user.id, "artifact-rebuild", status=BUILD_STATUS_QUEUED)

    assert second.id != first.id
    rows = db_session.exec(
        select(BuildORM).where(BuildORM.artifact_id == "artifact-rebuild")
    ).all()
    assert len(rows) == 2


def test_many_terminal_builds_may_share_one_artifact(db_session):
    """The index bounds concurrency, not history."""
    user = _user(db_session)
    for _ in range(3):
        build = _build(db_session, user.id, "artifact-history")
        build.transition_to(BUILD_STATUS_RUNNING)
        build.transition_to(BUILD_STATUS_FAILED)
        db_session.add(build)
        db_session.commit()

    rows = db_session.exec(
        select(BuildORM).where(BuildORM.artifact_id == "artifact-history")
    ).all()
    assert len(rows) == 3


def test_a_user_may_run_several_builds_of_different_artifacts_at_once(db_session):
    user = _user(db_session)
    first = _build(db_session, user.id, "artifact-one", status=BUILD_STATUS_RUNNING)
    second = _build(db_session, user.id, "artifact-two", status=BUILD_STATUS_QUEUED)

    assert first.id != second.id


# ---------------------------------------------------------------------------
# Ownership and the read/create contract
# ---------------------------------------------------------------------------


def test_a_build_belongs_to_a_deployment_and_records_no_owner(db_session):
    user = _user(db_session)
    build = _build(db_session, user.id, "artifact-owned")

    dumped = BuildRead.model_validate(build, from_attributes=True).model_dump()
    assert dumped["deployment_id"] == build.deployment_id
    assert "user_id" not in BuildORM.model_fields
    assert "user_id" not in dumped


def test_a_build_cannot_be_orphaned(db_session):
    db_session.add(BuildORM(artifact_id="artifact-orphan"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_a_deployment_may_run_two_builds_at_once(db_session):
    user = _user(db_session)
    first = _build(db_session, user.id, "artifact-first", status=BUILD_STATUS_RUNNING)
    second = _build(db_session, user.id, "artifact-second", status=BUILD_STATUS_QUEUED)

    assert first.deployment_id == second.deployment_id
    assert first.id != second.id


def test_build_create_accepts_only_an_artifact_id():
    assert set(BuildCreate.model_fields) == {"artifact_id"}

    payload = BuildCreate.model_validate({"artifact_id": "artifact-x"})
    assert payload.artifact_id == "artifact-x"


@pytest.mark.parametrize("field", ["user_id", "deployment_id"])
def test_build_create_rejects_a_caller_supplied_owner(field):
    """The deployment comes from the path and the owner from the deployment;
    either in the body is refused outright rather than quietly dropped."""
    with pytest.raises(Exception) as exc:
        BuildCreate.model_validate({"artifact_id": "artifact-x", field: 99})
    assert field in str(exc.value)


def test_build_read_exposes_no_job_id_or_log(db_session):
    """The Job name is a worker detail, and the log has its own endpoint."""
    user = _user(db_session)
    build = _build(db_session, user.id, "artifact-read", job_id="build-abc", log=b"noisy output")

    dumped = BuildRead.model_validate(build, from_attributes=True).model_dump()
    assert "job_id" not in dumped
    assert "log" not in dumped
    assert dumped["deployment_id"] == build.deployment_id
    assert dumped["artifact_id"] == "artifact-read"


def test_job_id_is_null_until_the_job_exists(db_session):
    user = _user(db_session)
    build = _build(db_session, user.id, "artifact-job")
    assert build.job_id is None

    build.transition_to(BUILD_STATUS_RUNNING)
    db_session.add(build)
    db_session.commit()
    db_session.refresh(build)
    # Still null: `running` with no Job is the recoverable state, not a race.
    assert build.job_id is None

    build.job_id = "build-" + str(build.id)
    db_session.add(build)
    db_session.commit()
    db_session.refresh(build)
    assert build.job_id == f"build-{build.id}"
