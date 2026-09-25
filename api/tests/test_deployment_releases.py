"""The release ledger: created by the request, completed by the reconciler.

Covers the write-path half — that every create and update mints exactly one
release, that a rejected write mints none, how a named build is validated, and
how status derives. The reconciler's half lives in the reconcile tests, and the
insert ordering the deferred foreign key permits is exercised in
test_deployment_release_ledger.py.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlmodel import select

from app.models import (
    BuildORM,
    DeploymentORM,
    DeploymentReconcileJobORM,
    DeploymentReleaseORM,
    ReleaseStatus,
)
from app.services.jobs import JobService
from app.services.reconcile_constants import DEPLOYMENT_STATUS_READY
from tests.conftest import client, db_session  # noqa: F401
from tests.conftest import create_free_plan_template, create_user, make_bare_deployment


SCHEMA = {
    "type": "object",
    "properties": {
        "host": {"type": "string", "title": "hostname"},
        "image": {"type": "string"},
    },
}


def _setup(client, db_session, email="rel@example.com"):
    """A user, a canonical template and a free plan — the minimum to deploy."""
    user_id = create_user(client, email)["id"]
    product_id = client.post(
        "/api/products", json={"name": f"prod-{email}", "description": "d"}
    ).json()["id"]
    template_id = client.post(
        f"/api/products/{product_id}/templates",
        json={
            "chart_ref": "oci://example/chart",
            "chart_version": "1.0.0",
            "values_schema_json": SCHEMA,
        },
    ).json()["id"]
    client.put(f"/api/products/{product_id}", json={"template_id": template_id})
    plan_template_id = create_free_plan_template(db_session, product_id)
    return user_id, template_id, plan_template_id


def _create(client, user_id, template_id, plan_template_id, values, **extra):
    return client.post(
        f"/api/users/{user_id}/deployments",
        json={
            "desired_template_id": template_id,
            "plan_template_id": plan_template_id,
            "user_values_json": values,
            **extra,
        },
    )


def _releases(db_session, deployment_id):
    return db_session.exec(
        select(DeploymentReleaseORM)
        .where(DeploymentReleaseORM.deployment_id == deployment_id)
        .order_by(DeploymentReleaseORM.number)
    ).all()


def _make_ready(db_session, deployment_id):
    """Stand in for a completed reconcile: close the open job, mark it ready.

    Both halves are needed before an update will be accepted -- `enqueue_job`
    rejects a second queued-or-running job, and `update_deployment` requires
    status ready/error. Together they are why `max(number) + 1` is safe.
    """
    deployment_id = UUID(str(deployment_id))
    open_job = db_session.exec(
        select(DeploymentReconcileJobORM)
        .where(DeploymentReconcileJobORM.deployment_id == deployment_id)
        .where(DeploymentReconcileJobORM.status.in_(("queued", "running")))
    ).first()
    if open_job is not None:
        JobService(db_session).mark_job_done(job_id=open_job.id)
    deployment = db_session.get(DeploymentORM, deployment_id)
    deployment.status = DEPLOYMENT_STATUS_READY
    db_session.add(deployment)
    db_session.commit()
    return deployment


def _build(db_session, *, deployment_id, image="7@sha256:" + "a" * 64):
    build = BuildORM(
        deployment_id=deployment_id,
        artifact_id=f"artifact-{uuid4().hex[:8]}",
        status="succeeded",
        image=image,
    )
    db_session.add(build)
    db_session.commit()
    return build


# ---------------------------------------------------------------------------
# A release is created by the request that asks for a rollout
# ---------------------------------------------------------------------------


def test_create_mints_release_one_and_points_the_deployment_at_it(client, db_session):
    user_id, template_id, plan_id = _setup(client, db_session)
    resp = _create(client, user_id, template_id, plan_id, {"host": "a.example.com"})
    assert resp.status_code == 201
    deployment_id = UUID(resp.json()["deployment"]["id"])

    releases = _releases(db_session, deployment_id)
    assert len(releases) == 1
    release = releases[0]
    assert release.number == 1

    deployment = db_session.get(DeploymentORM, deployment_id)
    assert deployment.desired_release_id == release.id
    # Nothing has rolled out yet, so the deployment is running nothing.
    assert deployment.applied_release_id is None


def test_release_snapshots_the_user_values_not_the_merged_values(client, db_session):
    user_id, template_id, plan_id = _setup(client, db_session, "snap@example.com")
    values = {"host": "snap.example.com", "image": "1@sha256:" + "b" * 64}
    resp = _create(client, user_id, template_id, plan_id, values)
    deployment_id = UUID(resp.json()["deployment"]["id"])

    release = _releases(db_session, deployment_id)[0]
    assert release.values_json == values
    # System overrides are the reconciler's and do not exist yet.
    assert "caelus" not in (release.values_json or {})


def test_release_records_the_template_it_is_to_be_applied_from(client, db_session):
    user_id, template_id, plan_id = _setup(client, db_session, "tpl@example.com")
    resp = _create(client, user_id, template_id, plan_id, {"host": "tpl.example.com"})
    deployment_id = UUID(resp.json()["deployment"]["id"])
    assert _releases(db_session, deployment_id)[0].template_id == template_id


def test_update_mints_a_second_release_and_moves_only_the_desired_pointer(client, db_session):
    user_id, template_id, plan_id = _setup(client, db_session, "upd@example.com")
    resp = _create(client, user_id, template_id, plan_id, {"host": "upd.example.com"})
    deployment_id = UUID(resp.json()["deployment"]["id"])
    first = _releases(db_session, deployment_id)[0]

    deployment = _make_ready(db_session, deployment_id)
    # Stand in for a reconciler that succeeded: it is running release 1.
    deployment.applied_release_id = first.id
    db_session.add(deployment)
    db_session.commit()

    resp = client.put(
        f"/api/users/{user_id}/deployments/{deployment_id}",
        json={
            "desired_template_id": template_id,
            "user_values_json": {"host": "upd2.example.com"},
        },
    )
    assert resp.status_code == 200

    releases = _releases(db_session, deployment_id)
    assert [r.number for r in releases] == [1, 2]
    db_session.expire_all()
    deployment = db_session.get(DeploymentORM, deployment_id)
    assert deployment.desired_release_id == releases[1].id
    # Asking for a rollout does not change what is running.
    assert deployment.applied_release_id == first.id


def test_two_identical_updates_produce_two_distinct_releases(client, db_session):
    user_id, template_id, plan_id = _setup(client, db_session, "twice@example.com")
    resp = _create(client, user_id, template_id, plan_id, {"host": "twice.example.com"})
    deployment_id = UUID(resp.json()["deployment"]["id"])
    body = {
        "desired_template_id": template_id,
        "user_values_json": {"host": "twice.example.com"},
    }

    for _ in range(2):
        _make_ready(db_session, deployment_id)
        assert client.put(
            f"/api/users/{user_id}/deployments/{deployment_id}", json=body
        ).status_code == 200

    releases = _releases(db_session, deployment_id)
    assert [r.number for r in releases] == [1, 2, 3]
    # Identity comes from the row, not the content.
    assert len({r.id for r in releases}) == 3
    assert releases[1].values_json == releases[2].values_json


def test_a_rejected_update_leaves_no_release_behind(client, db_session):
    user_id, template_id, plan_id = _setup(client, db_session, "guard@example.com")
    resp = _create(client, user_id, template_id, plan_id, {"host": "guard.example.com"})
    deployment_id = UUID(resp.json()["deployment"]["id"])
    # Deliberately not made ready: the status guard must reject the update.

    resp = client.put(
        f"/api/users/{user_id}/deployments/{deployment_id}",
        json={
            "desired_template_id": template_id,
            "user_values_json": {"host": "guard2.example.com"},
        },
    )
    assert resp.status_code == 409

    db_session.expire_all()
    assert len(_releases(db_session, deployment_id)) == 1


def test_release_numbers_are_per_deployment(client, db_session):
    user_id, template_id, plan_id = _setup(client, db_session, "perdep@example.com")
    first = UUID(
        _create(client, user_id, template_id, plan_id, {"host": "p1.example.com"})
        .json()["deployment"]["id"]
    )
    _make_ready(db_session, first)
    client.put(
        f"/api/users/{user_id}/deployments/{first}",
        json={"desired_template_id": template_id, "user_values_json": {"host": "p1b.example.com"}},
    )

    second = UUID(
        _create(client, user_id, template_id, plan_id, {"host": "p2.example.com"})
        .json()["deployment"]["id"]
    )
    # Numbering restarts, regardless of how many releases the first has.
    assert [r.number for r in _releases(db_session, second)] == [1]
    assert [r.number for r in _releases(db_session, first)] == [1, 2]


# ---------------------------------------------------------------------------
# The build reference belongs to the release alone
# ---------------------------------------------------------------------------


def _deployed(client, db_session, user_id, template_id, plan_id, host):
    """A ready deployment created without a build, as `freepod deploy` now does."""
    resp = _create(client, user_id, template_id, plan_id, {"host": host})
    assert resp.status_code == 201, resp.text
    deployment_id = UUID(resp.json()["deployment"]["id"])
    _make_ready(db_session, deployment_id)
    return deployment_id


def _release_with(client, user_id, deployment_id, template_id, host, build):
    return client.put(
        f"/api/users/{user_id}/deployments/{deployment_id}",
        json={
            "desired_template_id": template_id,
            "user_values_json": {"host": host, "image": build.image},
            "build_id": str(build.id),
        },
    )


def test_a_named_build_lands_on_the_release_and_not_on_the_deployment(client, db_session):
    user_id, template_id, plan_id = _setup(client, db_session, "build@example.com")
    deployment_id = _deployed(client, db_session, user_id, template_id, plan_id, "build.example.com")
    build = _build(db_session, deployment_id=deployment_id)

    resp = _release_with(client, user_id, deployment_id, template_id, "build.example.com", build)

    assert resp.status_code == 200, resp.text
    assert _releases(db_session, deployment_id)[-1].build_id == build.id
    # The deployment has no build-shaped state, on the row or in the response.
    assert not hasattr(db_session.get(DeploymentORM, deployment_id), "build_id")
    assert "build_id" not in resp.json()


def test_a_build_named_on_creation_is_rejected(client, db_session):
    """No build can belong to a deployment that does not exist yet."""
    user_id, template_id, plan_id = _setup(client, db_session, "early@example.com")
    elsewhere = _deployed(client, db_session, user_id, template_id, plan_id, "first.example.com")
    build = _build(db_session, deployment_id=elsewhere)

    resp = _create(
        client, user_id, template_id, plan_id,
        {"host": "second.example.com", "image": build.image},
        build_id=str(build.id),
    )

    assert resp.status_code == 400
    assert len(db_session.exec(select(DeploymentORM)).all()) == 1


def test_another_deployments_build_is_rejected(client, db_session):
    """Even the same owner's: the release would record another deployment's build."""
    user_id, template_id, plan_id = _setup(client, db_session, "mine@example.com")
    mine = _deployed(client, db_session, user_id, template_id, plan_id, "mine.example.com")
    sibling = _deployed(client, db_session, user_id, template_id, plan_id, "sibling.example.com")
    build = _build(db_session, deployment_id=sibling)

    resp = _release_with(client, user_id, mine, template_id, "mine.example.com", build)

    assert resp.status_code == 400
    assert [r.build_id for r in _releases(db_session, mine)] == [None]


def test_another_users_build_is_rejected(client, db_session):
    user_id, template_id, plan_id = _setup(client, db_session, "owner@example.com")
    mine = _deployed(client, db_session, user_id, template_id, plan_id, "owner.example.com")
    other_id = create_user(client, "theirs@example.com")["id"]
    stolen = _build(db_session, deployment_id=make_bare_deployment(db_session, other_id).id)

    resp = _release_with(client, user_id, mine, template_id, "owner.example.com", stolen)

    assert resp.status_code == 400
    assert [r.build_id for r in _releases(db_session, mine)] == [None]


def test_an_unknown_build_is_rejected_indistinguishably(client, db_session):
    user_id, template_id, plan_id = _setup(client, db_session, "ghost@example.com")
    mine = _deployed(client, db_session, user_id, template_id, plan_id, "ghost.example.com")
    sibling = _deployed(client, db_session, user_id, template_id, plan_id, "ghost2.example.com")
    theirs = _build(db_session, deployment_id=sibling)

    def put(build_id):
        return client.put(
            f"/api/users/{user_id}/deployments/{mine}",
            json={
                "desired_template_id": template_id,
                "user_values_json": {"host": "ghost.example.com"},
                "build_id": build_id,
            },
        )

    missing = put(str(uuid4()))
    elsewhere = put(str(theirs.id))

    assert missing.status_code == elsewhere.status_code == 400
    # Same answer for both, so the endpoint cannot be used to probe.
    assert missing.json() == elsewhere.json()


def test_an_image_reused_without_its_build_is_accepted(client, db_session):
    """Releasing another deployment's image is still possible, just without provenance."""
    user_id, template_id, plan_id = _setup(client, db_session, "reuse@example.com")
    mine = _deployed(client, db_session, user_id, template_id, plan_id, "reuse.example.com")
    sibling = _deployed(client, db_session, user_id, template_id, plan_id, "reuse2.example.com")
    build = _build(db_session, deployment_id=sibling)

    resp = client.put(
        f"/api/users/{user_id}/deployments/{mine}",
        json={
            "desired_template_id": template_id,
            "user_values_json": {"host": "reuse.example.com", "image": build.image},
        },
    )

    assert resp.status_code == 200, resp.text
    assert _releases(db_session, mine)[-1].build_id is None


def test_no_build_named_is_accepted_whatever_the_values_carry(client, db_session):
    """The admin UI's template-upgrade shape: stored values, image included, no build.

    Belonging is the only condition on a build reference, so a write that names
    none is accepted regardless of what the values contain. `image` is one
    chart's value, not a platform concept.
    """
    user_id, template_id, plan_id = _setup(client, db_session, "nobuild@example.com")
    resp = _create(
        client, user_id, template_id, plan_id,
        {"host": "nobuild.example.com", "image": "9@sha256:" + "c" * 64},
    )
    assert resp.status_code == 201
    deployment_id = UUID(resp.json()["deployment"]["id"])
    assert _releases(db_session, deployment_id)[0].build_id is None

    _make_ready(db_session, deployment_id)
    upgrade = client.put(
        f"/api/users/{user_id}/deployments/{deployment_id}",
        json={
            "desired_template_id": template_id,
            "user_values_json": {"host": "nobuild.example.com", "image": "9@sha256:" + "c" * 64},
        },
    )
    assert upgrade.status_code == 200


def test_a_build_is_accepted_for_a_deployment_whose_values_carry_no_image(client, db_session):
    user_id, template_id, plan_id = _setup(client, db_session, "curated@example.com")
    deployment_id = _deployed(client, db_session, user_id, template_id, plan_id, "curated.example.com")
    build = _build(db_session, deployment_id=deployment_id)

    resp = client.put(
        f"/api/users/{user_id}/deployments/{deployment_id}",
        json={
            "desired_template_id": template_id,
            "user_values_json": {"host": "curated.example.com"},
            "build_id": str(build.id),
        },
    )

    assert resp.status_code == 200, resp.text
    assert _releases(db_session, deployment_id)[-1].build_id == build.id


def test_update_records_the_build_it_was_given(client, db_session):
    user_id, template_id, plan_id = _setup(client, db_session, "updbuild@example.com")
    deployment_id = _deployed(client, db_session, user_id, template_id, plan_id, "ub.example.com")
    build = _build(db_session, deployment_id=deployment_id)

    resp = _release_with(client, user_id, deployment_id, template_id, "ub.example.com", build)

    assert resp.status_code == 200
    releases = _releases(db_session, deployment_id)
    assert releases[0].build_id is None
    assert releases[1].build_id == build.id


# ---------------------------------------------------------------------------
# Status is derived, never stored
# ---------------------------------------------------------------------------


def test_no_status_or_image_column_exists_on_the_ledger():
    columns = {c.name for c in DeploymentReleaseORM.__table__.columns}
    assert "status" not in columns
    assert "image" not in columns


@pytest.mark.parametrize(
    "started_delta, ended, error, expected",
    [
        (None, None, None, ReleaseStatus.QUEUED),
        (timedelta(seconds=5), None, None, ReleaseStatus.IN_FLIGHT),
        (timedelta(hours=3), None, None, ReleaseStatus.ABANDONED),
        (timedelta(seconds=5), True, "helm failed", ReleaseStatus.FAILED),
        (timedelta(seconds=5), True, None, ReleaseStatus.SUCCEEDED),
    ],
)
def test_release_status_derives_from_the_outcome_columns(started_delta, ended, error, expected):
    now = datetime.now(UTC)
    release = DeploymentReleaseORM(
        number=1,
        deployment_id=uuid4(),
        template_id=1,
        started_at=None if started_delta is None else now - started_delta,
        ended_at=now if ended else None,
        error=error,
    )
    assert release.status is expected


def test_in_flight_becomes_abandoned_past_the_reconcile_job_lease():
    """The lease, not the Helm timeout: a reconcile may legitimately spend the
    whole Helm budget, and the lease is already tuned to sit above it."""
    from app.config import get_settings

    lease = get_settings().reconcile_job_lease_seconds
    now = datetime.now(UTC)
    just_inside = DeploymentReleaseORM(
        number=1, deployment_id=uuid4(), template_id=1,
        started_at=now - timedelta(seconds=lease - 30),
    )
    just_outside = DeploymentReleaseORM(
        number=1, deployment_id=uuid4(), template_id=1,
        started_at=now - timedelta(seconds=lease + 30),
    )
    assert just_inside.status is ReleaseStatus.IN_FLIGHT
    assert just_outside.status is ReleaseStatus.ABANDONED


def test_status_tolerates_a_naive_started_at_as_postgres_returns_it():
    """Postgres hands back naive datetimes for a plain DateTime column while
    `_utcnow()` writes aware ones; comparing the two would raise."""
    release = DeploymentReleaseORM(
        number=1, deployment_id=uuid4(), template_id=1,
        started_at=datetime.now(UTC).replace(tzinfo=None),
    )
    assert release.status is ReleaseStatus.IN_FLIGHT


# ---------------------------------------------------------------------------
# The applied release is exposed on reads
# ---------------------------------------------------------------------------


def test_deployment_reads_expose_the_applied_release_without_deriving_it(client, db_session):
    user_id, template_id, plan_id = _setup(client, db_session, "read@example.com")
    deployment_id = UUID(
        _create(client, user_id, template_id, plan_id, {"host": "read.example.com"})
        .json()["deployment"]["id"]
    )

    # Nothing has rolled out yet: the deployment is running nothing.
    fresh = client.get(f"/api/users/{user_id}/deployments/{deployment_id}").json()
    assert fresh["applied_release"] is None

    # Stand in for a reconciler that succeeded.
    release = _releases(db_session, deployment_id)[0]
    deployment = db_session.get(DeploymentORM, deployment_id)
    deployment.applied_release_id = release.id
    db_session.add(deployment)
    db_session.commit()

    applied = client.get(f"/api/users/{user_id}/deployments/{deployment_id}").json()
    assert applied["applied_release"]["id"] == str(release.id)
    assert applied["applied_release"]["number"] == 1
    assert applied["applied_release"]["status"] == "queued"
    # Everything a caller needs about the running rollout is reachable through
    # it -- its template, its values, its build.
    assert applied["applied_release"]["template_id"] == template_id
    assert applied["applied_release"]["values_json"] == {"host": "read.example.com"}
    assert applied["applied_release"]["build_id"] is None

    # And across a listing, without a per-deployment derivation.
    listed = client.get(f"/api/users/{user_id}/deployments").json()
    assert listed[0]["applied_release"]["id"] == str(release.id)

    # Intent is deliberately not exposed as what is running.
    assert "desired_release" not in applied
