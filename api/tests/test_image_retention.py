"""The retention rule: which of an owner's images the ledger keeps.

Scenarios are the tenant-image-retention spec's, in its order.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlmodel import func, select

from app.config import CaelusSettings
from app.models import BuildORM, DeploymentORM, DeploymentReleaseORM, UserORM
from app.services import image_retention
from app.services.image_retention import APPLIED, DESIRED, EARLIER, FRESH, owner_retention
from tests.conftest import db_session, make_bare_deployment  # noqa: F401

SETTINGS = CaelusSettings()


def _image(owner_id: int, n: int) -> str:
    return f"{owner_id}@sha256:{n:064x}"


@pytest.fixture
def owner(db_session):
    user = UserORM(email=f"owner-{uuid4().hex[:8]}@example.com")
    db_session.add(user)
    db_session.commit()
    return user.id


def _ship(db_session, deployment, values, *, apply=True):
    """Add the deployment's next release carrying `values`, make it desired,
    and, by default, applied."""
    number = db_session.exec(
        select(func.max(DeploymentReleaseORM.number)).where(
            DeploymentReleaseORM.deployment_id == deployment.id
        )
    ).one()
    release = DeploymentReleaseORM(
        deployment_id=deployment.id,
        number=(number or 0) + 1,
        template_id=deployment.desired_template_id,
        values_json=values,
    )
    db_session.add(release)
    db_session.flush()
    deployment.desired_release_id = release.id
    if apply:
        deployment.applied_release_id = release.id
    db_session.add(deployment)
    db_session.commit()
    return release


def _retained(db_session, owner, **kw):
    return owner_retention(db_session, owner, SETTINGS, **kw).images


def test_the_running_image_is_retained(db_session, owner):
    d = make_bare_deployment(db_session, owner)
    _ship(db_session, d, {"image": _image(owner, 1)})
    assert _retained(db_session, owner) == {_image(owner, 1): APPLIED}


def test_a_rollout_in_progress_keeps_both_images(db_session, owner):
    d = make_bare_deployment(db_session, owner)
    _ship(db_session, d, {"image": _image(owner, 1)})
    _ship(db_session, d, {"image": _image(owner, 2)}, apply=False)
    assert _retained(db_session, owner) == {_image(owner, 2): DESIRED, _image(owner, 1): APPLIED}


def test_two_earlier_images_are_retained(db_session, owner):
    d = make_bare_deployment(db_session, owner)
    for n in range(1, 6):
        _ship(db_session, d, {"image": _image(owner, n)})
    assert _retained(db_session, owner) == {
        _image(owner, 5): APPLIED,
        _image(owner, 4): EARLIER,
        _image(owner, 3): EARLIER,
    }


def test_redeploying_one_image_counts_once(db_session, owner):
    d = make_bare_deployment(db_session, owner)
    _ship(db_session, d, {"image": _image(owner, 1)})
    _ship(db_session, d, {"image": _image(owner, 2)})
    for _ in range(10):
        _ship(db_session, d, {"image": _image(owner, 3), "note": "config change"})
    _ship(db_session, d, {"image": _image(owner, 4)})
    assert set(_retained(db_session, owner)) == {_image(owner, n) for n in (4, 3, 2)}


def test_a_failed_rollout_between_applied_and_desired_takes_no_earlier_slot(db_session, owner):
    """Releases 4 and 5 never applied; 5 is desired and carries the applied
    image again. The failed release 4 counts as earlier, and so do 2 and 3 --
    the applied image is not mistaken for an earlier one on the way down."""
    d = make_bare_deployment(db_session, owner)
    for n in (1, 2, 3):
        _ship(db_session, d, {"image": _image(owner, n)})
    _ship(db_session, d, {"image": _image(owner, 9)}, apply=False)
    _ship(db_session, d, {"image": _image(owner, 3)}, apply=False)
    assert _retained(db_session, owner) == {
        _image(owner, 3): APPLIED,
        _image(owner, 9): EARLIER,
        _image(owner, 2): EARLIER,
    }


def test_a_deleted_deployment_retains_nothing(db_session, owner):
    d = make_bare_deployment(db_session, owner)
    _ship(db_session, d, {"image": _image(owner, 1)})
    d.deleted_at = datetime.now(UTC)
    db_session.add(d)
    db_session.commit()
    assert _retained(db_session, owner) == {}


def test_an_image_shared_between_deployments(db_session, owner):
    builder = make_bare_deployment(db_session, owner)
    for n in range(1, 5):
        _ship(db_session, builder, {"image": _image(owner, n)})
    other = make_bare_deployment(db_session, owner)
    _ship(db_session, other, {"image": _image(owner, 1)})
    assert _retained(db_session, owner)[_image(owner, 1)] == APPLIED


def test_a_release_that_names_no_build_retains_its_image(db_session, owner):
    d = make_bare_deployment(db_session, owner)
    release = _ship(db_session, d, {"nested": {"workers": [{"image": _image(owner, 1)}]}})
    assert release.build_id is None
    assert _image(owner, 1) in _retained(db_session, owner)


def test_a_value_that_is_not_an_owner_image_retains_nothing(db_session, owner):
    d = make_bare_deployment(db_session, owner)
    _ship(
        db_session,
        d,
        {
            "other_owner": _image(owner + 1000, 1),
            "tagged": f"{owner}:latest",
            "prefixed": "x" + _image(owner, 2),
            "number": 7,
        },
    )
    assert _retained(db_session, owner) == {}


def test_an_owner_prefix_does_not_match_a_longer_owner_id(db_session, owner):
    d = make_bare_deployment(db_session, owner)
    _ship(db_session, d, {"image": f"{owner}1@sha256:{1:064x}"})
    assert _retained(db_session, owner) == {}


def _build(db_session, deployment, *, status="succeeded", image=None, finished_at=None):
    build = BuildORM(
        deployment_id=deployment.id,
        artifact_id=f"artifact-{uuid4().hex[:8]}",
        status=status,
        image=image,
        finished_at=finished_at,
    )
    db_session.add(build)
    db_session.commit()
    return build


def _naive(moment):
    return moment.astimezone(UTC).replace(tzinfo=None)


def test_a_build_that_just_finished_is_retained(db_session, owner):
    d = make_bare_deployment(db_session, owner)
    now = datetime.now(UTC)
    build = _build(
        db_session, d, image=_image(owner, 9), finished_at=_naive(now - timedelta(hours=1))
    )
    retention = owner_retention(db_session, owner, SETTINGS, now=now)
    assert retention.images == {_image(owner, 9): FRESH}
    assert build.id in retention.fresh_builds


def test_a_build_still_pushing_is_retained(db_session, owner):
    d = make_bare_deployment(db_session, owner)
    build = _build(db_session, d, status="running")
    assert build.id in owner_retention(db_session, owner, SETTINGS).fresh_builds


def test_a_build_never_deployed_past_the_grace_period_is_not_retained(db_session, owner):
    d = make_bare_deployment(db_session, owner)
    now = datetime.now(UTC)
    build = _build(
        db_session, d, image=_image(owner, 9), finished_at=_naive(now - timedelta(hours=25))
    )
    retention = owner_retention(db_session, owner, SETTINGS, now=now)
    assert retention.images == {}
    assert build.id not in retention.fresh_builds


def test_a_failed_build_is_not_fresh(db_session, owner):
    d = make_bare_deployment(db_session, owner)
    build = _build(db_session, d, status="failed", finished_at=_naive(datetime.now(UTC)))
    assert build.id not in owner_retention(db_session, owner, SETTINGS).fresh_builds


def test_other_owners_are_not_consulted(db_session, owner):
    stranger = UserORM(email=f"stranger-{uuid4().hex[:8]}@example.com")
    db_session.add(stranger)
    db_session.commit()
    d = make_bare_deployment(db_session, stranger.id)
    _ship(db_session, d, {"image": _image(stranger.id, 1)})
    assert _retained(db_session, owner) == {}


def test_the_past_image_count_is_a_setting(db_session, owner):
    d = make_bare_deployment(db_session, owner)
    for n in range(1, 6):
        _ship(db_session, d, {"image": _image(owner, n)})
    wider = CaelusSettings(registry_retained_past_images=4)
    assert len(owner_retention(db_session, owner, wider).images) == 5


def test_computing_retention_is_one_read(db_session, owner):
    d = make_bare_deployment(db_session, owner)
    _ship(db_session, d, {"image": _image(owner, 1)})
    _build(db_session, d, status="running")
    statements = []

    def record(conn, cursor, statement, *args):
        statements.append(statement.lstrip().split(None, 1)[0].lower())

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        owner_retention(db_session, owner, SETTINGS)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    # One query, and only a read.
    assert statements == ["select"]


def test_owner_images_finds_references_anywhere():
    values = {"a": [{"b": _image(3, 1)}], "c": _image(4, 2), "d": _image(3, 3)}
    assert image_retention.owner_images(3, values) == {_image(3, 1), _image(3, 3)}
