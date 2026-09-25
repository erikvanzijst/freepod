"""The release read API: listing, reading one by number, and what it inlines.

The write half of the ledger lives in test_deployment_releases.py. These build
release rows directly so that every derived status — including the time-derived
`abandoned` — is reachable without driving a reconciler.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlmodel import select

from app.config import get_settings
from app.models import (
    BuildORM,
    DeploymentORM,
    DeploymentReleaseORM,
    ReleaseStatus,
)
from app.services.build_constants import BUILD_STATUS_SUCCEEDED
from app.services.reconcile_constants import DEPLOYMENT_STATUS_DELETED
from tests.conftest import (  # noqa: F401
    AUTH_HEADER,
    OTHER_AUTH_HEADER,
    OTHER_EMAIL,
    USER_AUTH_HEADER,
    USER_EMAIL,
    client,
    create_user,
    db_session,
    make_deployment_with_release,
)

SCHEMA = {"type": "object", "properties": {"image": {"type": "string"}}}


def _template(client, name):
    product_id = client.post(
        "/api/products", json={"name": name, "description": "d"}
    ).json()["id"]
    return client.post(
        f"/api/products/{product_id}/templates",
        json={
            "chart_ref": "oci://example/chart",
            "chart_version": "1.0.0",
            "values_schema_json": SCHEMA,
        },
    ).json()["id"]


def _deployment(client, db_session, *, user_id, template_id, name="dep"):
    deployment = make_deployment_with_release(
        db_session,
        user_id=user_id,
        desired_template_id=template_id,
        name=name,
        namespace=f"ns-{name}",
    )
    db_session.commit()
    db_session.refresh(deployment)
    return deployment


def _build(db_session, *, deployment_id, image="reg/app@sha256:" + "a" * 64):
    build = BuildORM(
        deployment_id=deployment_id,
        artifact_id="f" * 32,
        status=BUILD_STATUS_SUCCEEDED,
        image=image,
    )
    db_session.add(build)
    db_session.commit()
    db_session.refresh(build)
    return build


def _release(db_session, deployment, number, **kwargs):
    release = DeploymentReleaseORM(
        id=uuid4(),
        deployment_id=deployment.id,
        number=number,
        template_id=deployment.desired_template_id,
        **kwargs,
    )
    db_session.add(release)
    db_session.commit()
    db_session.refresh(release)
    return release


def _url(user_id, deployment_id, *suffix):
    base = f"/api/users/{user_id}/deployments/{deployment_id}/releases"
    return "/".join((base, *(str(p) for p in suffix)))


@pytest.fixture
def scenario(client, db_session):
    """One user, one deployment, releases 1..3 — 1 and 2 done, 3 queued."""
    user = create_user(client, USER_EMAIL)
    template_id = _template(client, "relprod")
    deployment = _deployment(
        client, db_session, user_id=user["id"], template_id=template_id
    )
    started = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    first = db_session.exec(
        select(DeploymentReleaseORM).where(
            DeploymentReleaseORM.deployment_id == deployment.id
        )
    ).one()
    first.started_at = started
    first.ended_at = started + timedelta(seconds=30)
    db_session.add(first)
    db_session.commit()

    build = _build(db_session, deployment_id=deployment.id)
    _release(
        db_session,
        deployment,
        2,
        build_id=build.id,
        started_at=started + timedelta(minutes=5),
        ended_at=started + timedelta(minutes=6),
        error="helm upgrade failed",
    )
    _release(db_session, deployment, 3)
    return {"user": user, "deployment": deployment, "template_id": template_id, "build": build}


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def test_releases_are_listed_highest_number_first(client, scenario):
    resp = client.get(
        _url(scenario["user"]["id"], scenario["deployment"].id), headers=USER_AUTH_HEADER
    )

    assert resp.status_code == 200, resp.text
    assert [r["number"] for r in resp.json()] == [3, 2, 1]


def test_every_outcome_appears_in_the_listing(client, scenario):
    body = client.get(
        _url(scenario["user"]["id"], scenario["deployment"].id), headers=USER_AUTH_HEADER
    ).json()

    by_number = {r["number"]: r["status"] for r in body}
    assert by_number == {
        3: ReleaseStatus.QUEUED,
        2: ReleaseStatus.FAILED,
        1: ReleaseStatus.SUCCEEDED,
    }


def test_another_deployments_releases_do_not_appear(client, db_session, scenario):
    user_id = scenario["user"]["id"]
    second = _deployment(
        client, db_session, user_id=user_id, template_id=scenario["template_id"], name="dep2"
    )

    body = client.get(_url(user_id, second.id), headers=USER_AUTH_HEADER).json()

    assert [r["number"] for r in body] == [1]
    assert {r["deployment_id"] for r in body} == {str(second.id)}


# ---------------------------------------------------------------------------
# Reading one, by number
# ---------------------------------------------------------------------------


def test_a_release_is_read_by_its_number(client, scenario):
    resp = client.get(
        _url(scenario["user"]["id"], scenario["deployment"].id, 2), headers=USER_AUTH_HEADER
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["number"] == 2
    assert body["status"] == ReleaseStatus.FAILED
    assert body["error"] == "helm upgrade failed"


def test_a_number_the_deployment_never_reached_is_not_found(client, scenario):
    resp = client.get(
        _url(scenario["user"]["id"], scenario["deployment"].id, 9), headers=USER_AUTH_HEADER
    )

    assert resp.status_code == 404


def test_the_uuid_is_not_accepted_in_place_of_the_number(client, db_session, scenario):
    release = db_session.exec(
        select(DeploymentReleaseORM)
        .where(DeploymentReleaseORM.deployment_id == scenario["deployment"].id)
        .where(DeploymentReleaseORM.number == 2)
    ).one()

    resp = client.get(
        _url(scenario["user"]["id"], scenario["deployment"].id, release.id),
        headers=USER_AUTH_HEADER,
    )

    assert resp.status_code == 422


def test_a_number_is_scoped_to_its_own_deployment(client, db_session, scenario):
    user_id = scenario["user"]["id"]
    second = _deployment(
        client, db_session, user_id=user_id, template_id=scenario["template_id"], name="dep2"
    )

    first_one = client.get(
        _url(user_id, scenario["deployment"].id, 1), headers=USER_AUTH_HEADER
    ).json()
    second_one = client.get(_url(user_id, second.id, 1), headers=USER_AUTH_HEADER).json()

    assert first_one["deployment_id"] == str(scenario["deployment"].id)
    assert second_one["deployment_id"] == str(second.id)
    assert first_one["id"] != second_one["id"]


# ---------------------------------------------------------------------------
# The inlined build
# ---------------------------------------------------------------------------


def test_a_single_release_inlines_the_build_it_shipped(client, scenario):
    body = client.get(
        _url(scenario["user"]["id"], scenario["deployment"].id, 2), headers=USER_AUTH_HEADER
    ).json()

    assert body["build_id"] == str(scenario["build"].id)
    assert body["build"]["id"] == str(scenario["build"].id)
    assert body["build"]["image"] == scenario["build"].image
    assert body["build"]["status"] == BUILD_STATUS_SUCCEEDED


def test_the_listing_inlines_the_build_on_every_row(client, scenario):
    body = client.get(
        _url(scenario["user"]["id"], scenario["deployment"].id), headers=USER_AUTH_HEADER
    ).json()

    shipped = next(r for r in body if r["number"] == 2)
    assert shipped["build"]["image"] == scenario["build"].image


def test_a_release_naming_no_build_reports_none_and_is_still_listed(client, scenario):
    """The join is outer: most products build nothing, and those rows must stay."""
    body = client.get(
        _url(scenario["user"]["id"], scenario["deployment"].id), headers=USER_AUTH_HEADER
    ).json()

    buildless = [r for r in body if r["number"] in (1, 3)]
    assert len(buildless) == 2
    assert all(r["build_id"] is None and r["build"] is None for r in buildless)

    single = client.get(
        _url(scenario["user"]["id"], scenario["deployment"].id, 1), headers=USER_AUTH_HEADER
    ).json()
    assert single["build"] is None


# ---------------------------------------------------------------------------
# Query count
# ---------------------------------------------------------------------------


def _count_selects(session, fn):
    """How many SELECTs `fn` causes on the session's engine."""
    seen = []

    def record(conn, cursor, statement, params, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            seen.append(statement)

    engine = session.get_bind()
    event.listen(engine, "after_cursor_execute", record)
    try:
        fn()
    finally:
        event.remove(engine, "after_cursor_execute", record)
    return seen


def test_listing_many_releases_does_not_multiply_queries(client, db_session, scenario):
    """The whole point of the eager join: query count is flat in release count."""
    user_id = scenario["user"]["id"]
    url = _url(user_id, scenario["deployment"].id)

    def read():
        assert client.get(url, headers=USER_AUTH_HEADER).status_code == 200

    few = len(_count_selects(db_session, read))

    for number in range(4, 14):
        build = _build(
            db_session,
            deployment_id=scenario["deployment"].id,
            image=f"reg/app@sha256:{number:064d}",
        )
        _release(db_session, scenario["deployment"], number, build_id=build.id)

    many = len(_count_selects(db_session, read))

    assert client.get(url, headers=USER_AUTH_HEADER).json().__len__() == 13
    assert many == few, f"query count grew with release count: {few} -> {many}"


def test_a_deployment_listing_still_does_not_load_builds(client, db_session, scenario):
    """The relationship is `lazy="raise"` precisely so this cannot regress."""
    user_id = scenario["user"]["id"]

    def read():
        assert client.get(
            f"/api/users/{user_id}/deployments", headers=USER_AUTH_HEADER
        ).status_code == 200

    statements = _count_selects(db_session, read)

    assert not any(" build " in s or "JOIN build" in s for s in statements), statements


# ---------------------------------------------------------------------------
# Derived status
# ---------------------------------------------------------------------------


def test_a_release_that_never_started_is_queued(client, scenario):
    body = client.get(
        _url(scenario["user"]["id"], scenario["deployment"].id, 3), headers=USER_AUTH_HEADER
    ).json()

    assert body["status"] == ReleaseStatus.QUEUED
    assert body["started_at"] is None and body["ended_at"] is None and body["error"] is None


def test_a_release_still_within_its_lease_is_in_flight(client, db_session, scenario):
    _release(db_session, scenario["deployment"], 4, started_at=datetime.now(UTC))

    body = client.get(
        _url(scenario["user"]["id"], scenario["deployment"].id, 4), headers=USER_AUTH_HEADER
    ).json()

    assert body["status"] == ReleaseStatus.IN_FLIGHT


def test_a_release_past_its_lease_is_abandoned(client, db_session, scenario):
    lease = get_settings().reconcile_job_lease_seconds
    _release(
        db_session,
        scenario["deployment"],
        4,
        started_at=datetime.now(UTC) - timedelta(seconds=lease + 60),
    )

    body = client.get(
        _url(scenario["user"]["id"], scenario["deployment"].id, 4), headers=USER_AUTH_HEADER
    ).json()

    assert body["status"] == ReleaseStatus.ABANDONED


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


def test_naming_another_account_is_forbidden(client, scenario):
    create_user(client, OTHER_EMAIL)

    listing = client.get(
        _url(scenario["user"]["id"], scenario["deployment"].id), headers=OTHER_AUTH_HEADER
    )
    single = client.get(
        _url(scenario["user"]["id"], scenario["deployment"].id, 1), headers=OTHER_AUTH_HEADER
    )

    assert listing.status_code == single.status_code == 403


def test_a_foreign_deployment_under_your_own_account_is_not_found(client, scenario):
    """404, not 403 — a deployment that is not yours reads like one that is not
    there, so the endpoint cannot be used to probe."""
    other = create_user(client, OTHER_EMAIL)

    resp = client.get(
        _url(other["id"], scenario["deployment"].id), headers=OTHER_AUTH_HEADER
    )
    absent = client.get(_url(other["id"], uuid4()), headers=OTHER_AUTH_HEADER)

    assert resp.status_code == absent.status_code == 404
    assert resp.json() == absent.json()


def test_an_admin_reads_any_deployments_releases(client, scenario):
    resp = client.get(
        _url(scenario["user"]["id"], scenario["deployment"].id), headers=AUTH_HEADER
    )

    assert resp.status_code == 200
    assert [r["number"] for r in resp.json()] == [3, 2, 1]


def test_a_deleted_deployments_releases_are_not_found(client, db_session, scenario):
    deployment = db_session.get(DeploymentORM, scenario["deployment"].id)
    deployment.status = DEPLOYMENT_STATUS_DELETED
    db_session.add(deployment)
    db_session.commit()

    user_id = scenario["user"]["id"]
    assert client.get(_url(user_id, deployment.id), headers=USER_AUTH_HEADER).status_code == 404
    assert client.get(_url(user_id, deployment.id, 1), headers=USER_AUTH_HEADER).status_code == 404
