"""A deployment's own name, description and icon; the release rule; managed
fields (deployment-identity, deployment-project-file, edit-deployment-backend)."""

from __future__ import annotations

import base64
import io
import os
from datetime import UTC, datetime
from uuid import UUID

import pytest
from PIL import Image
from sqlmodel import select

from app.models import (
    DeploymentORM,
    DeploymentReconcileJobORM,
    DeploymentReleaseORM,
    MolliePaymentORM,
    SubscriptionORM,
)
from app.services import deployment_identity
from app.services.jobs import JobService
from tests.conftest import (
    OTHER_EMAIL,
    auth_header,
    client,  # noqa: F401
    create_free_plan_template,
    create_paid_plan_template,
    create_user,
    db_session,  # noqa: F401
    fake_payment_provider,  # noqa: F401
    paid_client,  # noqa: F401
)

OWNER = "owner@example.com"

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "host": {"type": "string", "title": "hostname"},
        "image": {"type": "string"},
        "LOG_LEVEL": {"type": "string", "x-caelus-target": "runtime"},
        "auth": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"enabled": {"type": "boolean"}, "access": {"type": "string"}},
        },
    },
}


def _product(client, db_session, name="Nextcloud", *, paid=False):
    product_id = client.post("/api/products", json={"name": name, "description": "d"}).json()["id"]
    template_id = client.post(
        f"/api/products/{product_id}/templates",
        json={"chart_ref": "oci://example/chart", "chart_version": "1.0.0", "values_schema_json": SCHEMA},
    ).json()["id"]
    client.put(f"/api/products/{product_id}", json={"template_id": template_id})
    plan_id = (
        create_paid_plan_template(db_session, product_id)
        if paid
        else create_free_plan_template(db_session, product_id)
    )
    return template_id, plan_id


@pytest.fixture
def setup(client, db_session):
    user_id = create_user(client, OWNER)["id"]
    template_id, plan_id = _product(client, db_session)
    return user_id, template_id, plan_id


def _create(client, setup, host, *, email=OWNER, **extra):
    user_id, template_id, plan_id = setup
    return client.post(
        f"/api/users/{user_id}/deployments",
        json={
            "desired_template_id": template_id,
            "plan_template_id": plan_id,
            "user_values_json": {"host": host},
            **extra,
        },
        headers=auth_header(email),
    )


def _created(client, setup, host, **extra) -> dict:
    resp = _create(client, setup, host, **extra)
    assert resp.status_code == 201, resp.text
    return resp.json()["deployment"]


def _ready(db_session, deployment_id) -> None:
    deployment_id = UUID(str(deployment_id))
    open_job = db_session.exec(
        select(DeploymentReconcileJobORM)
        .where(DeploymentReconcileJobORM.deployment_id == deployment_id)
        .where(DeploymentReconcileJobORM.status.in_(("queued", "running")))
    ).first()
    if open_job is not None:
        JobService(db_session).mark_job_done(job_id=open_job.id)
    row = db_session.get(DeploymentORM, deployment_id)
    row.status = "ready"
    row.applied_release_id = row.desired_release_id
    db_session.add(row)
    db_session.commit()


def _put(client, setup, deployment_id, *, email=OWNER, **body):
    user_id = setup[0]
    return client.put(
        f"/api/users/{user_id}/deployments/{deployment_id}", json=body, headers=auth_header(email)
    )


def _release_count(db_session, deployment_id) -> int:
    return len(
        db_session.exec(
            select(DeploymentReleaseORM).where(DeploymentReleaseORM.deployment_id == UUID(str(deployment_id)))
        ).all()
    )


def _queued_jobs(db_session, deployment_id) -> int:
    return len(
        db_session.exec(
            select(DeploymentReconcileJobORM)
            .where(DeploymentReconcileJobORM.deployment_id == UUID(str(deployment_id)))
            .where(DeploymentReconcileJobORM.status == "queued")
        ).all()
    )


def _image(fmt: str, size=(64, 64)) -> str:
    out = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(out, format=fmt)
    return base64.b64encode(out.getvalue()).decode()


# ── Names ────────────────────────────────────────────────────────────────


def test_a_name_is_trimmed_and_kept_as_entered(client, setup):
    assert _created(client, setup, "a.example.com", name="  Family photos ")["name"] == "Family photos"


@pytest.mark.parametrize("name", ["two\nlines", "   ", "x" * 101])
def test_an_invalid_name_is_refused(client, db_session, setup, name):
    resp = _create(client, setup, "a.example.com", name=name)
    assert (resp.status_code, resp.json()["code"]) == (400, "invalid_name")
    assert db_session.exec(select(DeploymentORM)).all() == []


def test_a_duplicate_name_is_refused_ignoring_case(client, setup):
    _created(client, setup, "a.example.com", name="Arkanoid")
    resp = _create(client, setup, "b.example.com", name="arkanoid")
    assert (resp.status_code, resp.json()["code"]) == (409, "name_in_use")


def test_two_owners_may_share_a_name(client, db_session, setup):
    _created(client, setup, "a.example.com", name="Arkanoid")
    other_id = create_user(client, OTHER_EMAIL)["id"]
    other = (other_id, setup[1], setup[2])
    assert _created(client, other, "b.example.com", email=OTHER_EMAIL, name="Arkanoid")["name"] == "Arkanoid"


def test_a_deleted_deployments_name_is_free(client, db_session, setup):
    first = _created(client, setup, "a.example.com", name="Arkanoid")
    row = db_session.get(DeploymentORM, UUID(first["id"]))
    row.status = "deleted"
    db_session.add(row)
    db_session.commit()
    assert _created(client, setup, "b.example.com", name="Arkanoid")["name"] == "Arkanoid"


def test_an_unnamed_deployment_is_named_after_its_product(client, setup):
    assert _created(client, setup, "a.example.com")["name"] == "Nextcloud"
    assert _created(client, setup, "b.example.com")["name"] == "Nextcloud 2"


def test_a_taken_name_refuses_a_paid_create_before_checkout(
    paid_client, db_session, fake_payment_provider
):
    user_id = create_user(paid_client, OWNER)["id"]
    template_id, plan_id = _product(paid_client, db_session, "Paid", paid=True)
    setup = (user_id, template_id, plan_id)
    first = _create(paid_client, setup, "a.example.com", name="Arkanoid")
    assert first.status_code == 201, first.text
    payments = len(fake_payment_provider.payments)
    subscriptions = len(db_session.exec(select(SubscriptionORM)).all())

    resp = _create(paid_client, setup, "b.example.com", name="ARKANOID")

    assert (resp.status_code, resp.json()["code"]) == (409, "name_in_use")
    assert len(fake_payment_provider.payments) == payments
    assert len(db_session.exec(select(SubscriptionORM)).all()) == subscriptions
    assert len(db_session.exec(select(DeploymentORM)).all()) == 1
    assert len(db_session.exec(select(MolliePaymentORM)).all()) == 1


def test_a_rename_of_a_running_app_changes_nothing_else(client, db_session, setup):
    created = _created(client, setup, "a.example.com", name="arkanoid")
    _ready(db_session, created["id"])
    before = db_session.get(DeploymentORM, UUID(created["id"]))
    release_name, hostname, desired = before.name, before.hostname, before.desired_release_id

    resp = _put(client, setup, created["id"], name="Arkanoid: Space Edition")

    assert resp.status_code == 200, resp.text
    assert (resp.json()["name"], resp.json()["status"]) == ("Arkanoid: Space Edition", "ready")
    db_session.expire_all()
    after = db_session.get(DeploymentORM, UUID(created["id"]))
    assert (after.name, after.hostname, after.desired_release_id) == (release_name, hostname, desired)
    assert _release_count(db_session, created["id"]) == 1
    assert _queued_jobs(db_session, created["id"]) == 0


def test_a_rename_into_a_taken_name_is_refused(client, db_session, setup):
    _created(client, setup, "a.example.com", name="Arkanoid")
    second = _created(client, setup, "b.example.com", name="Pong")
    resp = _put(client, setup, second["id"], name="ARKANOID")
    assert (resp.status_code, resp.json()["code"]) == (409, "name_in_use")


def test_a_case_only_rename_of_the_same_deployment_is_accepted(client, db_session, setup):
    created = _created(client, setup, "a.example.com", name="arkanoid")
    assert _put(client, setup, created["id"], name="Arkanoid").json()["name"] == "Arkanoid"


def test_a_rename_while_provisioning_keeps_the_status(client, db_session, setup):
    created = _created(client, setup, "a.example.com")
    resp = _put(client, setup, created["id"], name="Recipes")
    assert resp.status_code == 200, resp.text
    assert (resp.json()["name"], resp.json()["status"]) == ("Recipes", "provisioning")
    assert _release_count(db_session, created["id"]) == 1


def test_a_deployment_being_deleted_cannot_be_renamed(client, db_session, setup):
    created = _created(client, setup, "a.example.com")
    row = db_session.get(DeploymentORM, UUID(created["id"]))
    row.status = "deleting"
    db_session.add(row)
    db_session.commit()
    assert _put(client, setup, created["id"], name="Recipes").status_code == 409


def test_another_users_rename_is_refused(client, db_session, setup):
    created = _created(client, setup, "a.example.com")
    create_user(client, OTHER_EMAIL)
    resp = _put(client, setup, created["id"], email=OTHER_EMAIL, name="Mine now")
    assert resp.status_code == 403


# ── Description ──────────────────────────────────────────────────────────


def test_a_description_only_update_creates_no_release(client, db_session, setup):
    created = _created(client, setup, "a.example.com")
    _ready(db_session, created["id"])
    resp = _put(client, setup, created["id"], description="Our family's photos")
    assert resp.json()["description"] == "Our family's photos"
    assert _release_count(db_session, created["id"]) == 1
    cleared = _put(client, setup, created["id"], description=None)
    assert cleared.json()["description"] is None


def test_a_long_description_is_refused(client, setup):
    resp = _create(client, setup, "a.example.com", description="x" * 501)
    assert (resp.status_code, resp.json()["code"]) == (400, "invalid_description")


# ── Icon ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_a_raster_icon_is_stored_re_encoded_as_png(client, db_session, setup, fmt, tmp_path, monkeypatch):
    monkeypatch.setenv("CAELUS_STATIC_PATH", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    created = _created(client, setup, "a.example.com", icon=_image(fmt))
    get_settings.cache_clear()
    assert created["icon_url"].startswith("/api/static/icons/")
    row = db_session.get(DeploymentORM, UUID(created["id"]))
    with Image.open(tmp_path / row.rel_icon_path) as img:
        assert img.format == "PNG"


def test_a_large_png_is_scaled_to_256(client, db_session, setup, tmp_path, monkeypatch):
    monkeypatch.setenv("CAELUS_STATIC_PATH", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    created = _created(client, setup, "a.example.com", icon=_image("PNG", (1024, 1024)))
    get_settings.cache_clear()
    row = db_session.get(DeploymentORM, UUID(created["id"]))
    with Image.open(tmp_path / row.rel_icon_path) as img:
        assert max(img.size) <= 256


def test_an_svg_icon_is_refused(client, setup):
    svg = base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg"/>').decode()
    resp = _create(client, setup, "a.example.com", icon=svg)
    assert (resp.status_code, resp.json()["code"]) == (400, "invalid_icon")


def test_an_oversized_icon_is_refused_naming_the_limit(client, setup):
    big = base64.b64encode(b"\x89PNG\r\n\x1a\n" + os.urandom(256 * 1024)).decode()
    resp = _create(client, setup, "a.example.com", icon=big)
    assert (resp.status_code, resp.json()["code"]) == (400, "invalid_icon")
    assert "256 KiB" in resp.json()["detail"]


def test_the_same_icon_again_is_not_re_encoded(client, db_session, setup, monkeypatch):
    icon = _image("PNG")
    created = _created(client, setup, "a.example.com", icon=icon)
    calls = []
    monkeypatch.setattr(deployment_identity, "process_icon", lambda data: calls.append(data))
    resp = _put(client, setup, created["id"], icon=icon)
    assert resp.status_code == 200, resp.text
    assert resp.json()["icon_url"] == created["icon_url"]
    assert calls == []


def test_a_null_icon_clears_it(client, db_session, setup):
    created = _created(client, setup, "a.example.com", icon=_image("PNG"))
    resp = _put(client, setup, created["id"], icon=None)
    assert resp.json()["icon_url"] is None
    row = db_session.get(DeploymentORM, UUID(created["id"]))
    db_session.refresh(row)
    assert (row.rel_icon_path, row.icon_source_sha256) == (None, None)


# ── Reads ────────────────────────────────────────────────────────────────


def test_reads_report_the_identity_and_no_release_name(client, db_session, setup):
    created = _created(client, setup, "a.example.com")
    release_name = db_session.get(DeploymentORM, UUID(created["id"])).name
    user_id = setup[0]
    single = client.get(f"/api/users/{user_id}/deployments/{created['id']}", headers=auth_header(OWNER)).json()
    [listed] = client.get(f"/api/users/{user_id}/deployments", headers=auth_header(OWNER)).json()
    for read in (created, single, listed):
        assert read["name"] == "Nextcloud"
        assert (read["description"], read["icon_url"], read["managed_fields"]) == (None, None, [])
        assert release_name not in str(read)
        assert read["desired_template"]["product"]["name"] == "Nextcloud"


# ── The release rule ─────────────────────────────────────────────────────


def test_an_update_without_a_template_keeps_the_current_one(client, db_session, setup):
    created = _created(client, setup, "a.example.com")
    _ready(db_session, created["id"])
    resp = _put(client, setup, created["id"], user_values_json={"host": "a.example.com", "auth": {"enabled": True}})
    assert resp.status_code == 200, resp.text
    assert resp.json()["desired_template_id"] == setup[1]
    assert _release_count(db_session, created["id"]) == 2


def test_chart_values_and_a_build_make_one_release(client, db_session, setup):
    from app.models import BuildORM

    created = _created(client, setup, "a.example.com")
    _ready(db_session, created["id"])
    image = "7@sha256:" + "a" * 64
    build = BuildORM(
        deployment_id=UUID(created["id"]),
        artifact_id="artifact-x",
        status="succeeded",
        image=image,
        finished_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db_session.add(build)
    db_session.commit()
    resp = _put(
        client, setup, created["id"],
        user_values_json={"host": "a.example.com", "image": image, "auth": {"enabled": True}},
        build_id=str(build.id),
    )
    assert resp.status_code == 200, resp.text
    releases = db_session.exec(
        select(DeploymentReleaseORM).where(DeploymentReleaseORM.deployment_id == UUID(created["id"]))
    ).all()
    assert len(releases) == 2
    latest = max(releases, key=lambda r: r.number)
    assert latest.build_id == build.id
    assert latest.values_json["auth"] == {"enabled": True}


def test_staged_vars_make_an_unchanged_update_release(client, db_session, setup):
    created = _created(client, setup, "a.example.com")
    _ready(db_session, created["id"])
    url = f"/api/users/{setup[0]}/deployments/{created['id']}"
    staged = client.patch(
        f"{url}/vars/runtime", json={"vars": {"LOG_LEVEL": {"value": "trace"}}}, headers=auth_header(OWNER)
    )
    assert staged.status_code == 200, staged.text
    assert _release_count(db_session, created["id"]) == 1

    resp = _put(client, setup, created["id"], user_values_json={"host": "a.example.com"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "provisioning"
    assert _release_count(db_session, created["id"]) == 2


def test_vars_set_at_create_do_not_stage_a_rename_while_provisioning(client, db_session, setup):
    created = _created(client, setup, "a.example.com", vars={"LOG_LEVEL": {"value": "debug"}})
    resp = _put(client, setup, created["id"], name="Renamed")
    assert resp.status_code == 200, resp.text
    assert _release_count(db_session, created["id"]) == 1


def test_an_unchanged_update_to_a_ready_deployment_is_a_no_op(client, db_session, setup):
    created = _created(client, setup, "a.example.com")
    _ready(db_session, created["id"])
    resp = _put(client, setup, created["id"], desired_template_id=setup[1], user_values_json={"host": "a.example.com"})
    assert resp.json()["status"] == "ready"
    assert _release_count(db_session, created["id"]) == 1
    assert _queued_jobs(db_session, created["id"]) == 0


# ── Managed fields ───────────────────────────────────────────────────────


def test_a_create_sets_managed_fields(client, setup):
    created = _created(client, setup, "a.example.com", managed_fields=["auth"])
    assert created["managed_fields"] == ["auth"]


def test_an_update_claims_and_gives_up_fields(client, db_session, setup):
    created = _created(client, setup, "a.example.com")
    _ready(db_session, created["id"])
    claimed = _put(
        client, setup, created["id"],
        user_values_json={"host": "a.example.com", "auth": {"enabled": True}},
        managed_fields=["name", "auth"],
    )
    assert claimed.json()["managed_fields"] == ["name", "auth"]
    _ready(db_session, created["id"])
    given_up = _put(client, setup, created["id"], managed_fields=["name"])
    assert given_up.json()["managed_fields"] == ["name"]
    assert given_up.json()["user_values_json"]["auth"] == {"enabled": True}


def test_an_unknown_managed_key_is_refused(client, db_session, setup):
    created = _created(client, setup, "a.example.com")
    resp = _put(client, setup, created["id"], managed_fields=["auht"])
    assert (resp.status_code, resp.json()["code"]) == (400, "invalid_managed_fields")
    db_session.expire_all()
    assert db_session.get(DeploymentORM, UUID(created["id"])).managed_fields == []


@pytest.mark.parametrize("email", [OWNER, "test@example.com"])
def test_a_managed_name_cannot_be_changed_without_the_list(client, db_session, setup, email):
    created = _created(client, setup, "a.example.com", name="Arkanoid", managed_fields=["name"])
    resp = _put(client, setup, created["id"], email=email, name="Pong")
    assert (resp.status_code, resp.json()["code"]) == (409, "managed_by_project_file")
    assert "'name'" in resp.json()["detail"]


def test_a_managed_chart_value_cannot_be_changed_without_the_list(client, db_session, setup):
    created = _created(client, setup, "a.example.com", managed_fields=["auth"])
    _ready(db_session, created["id"])
    resp = _put(client, setup, created["id"], user_values_json={"host": "a.example.com", "auth": {"enabled": True}})
    assert (resp.status_code, resp.json()["code"]) == (409, "managed_by_project_file")


def test_an_update_around_a_managed_field_is_accepted(client, db_session, setup):
    created = _created(client, setup, "a.example.com", managed_fields=["auth"])
    _ready(db_session, created["id"])
    resp = _put(client, setup, created["id"], user_values_json={"host": "b.example.com"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["hostname"] == "b.example.com"


def test_a_take_over_keeps_the_value_and_the_file_can_claim_it_back(client, db_session, setup):
    created = _created(client, setup, "a.example.com", description="From the file", managed_fields=["description"])
    taken = _put(client, setup, created["id"], managed_fields=[])
    assert (taken.json()["managed_fields"], taken.json()["description"]) == ([], "From the file")
    assert _put(client, setup, created["id"], description="Edited").status_code == 200
    back = _put(client, setup, created["id"], description="From the file again", managed_fields=["description"])
    assert (back.json()["managed_fields"], back.json()["description"]) == (["description"], "From the file again")
