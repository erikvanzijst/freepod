"""The hostname check for flat tenant hostnames: a bare label is completed
beneath the caller's handle, and a tenant name must end in it."""

import pytest
from sqlmodel import select

from app.config import CaelusSettings
from app.models import UserORM
from tests.conftest import OTHER_EMAIL, USER_EMAIL, create_user, make_deployment_with_release
from tests.test_hostnames import seed_parents  # noqa: F401

SETTINGS = CaelusSettings(
    domain="",
    tenant_domain="freepod.app",
    platform_domains=["freepod.eu", "freepod.app"],
    _env_file=None,
)


@pytest.fixture
def tenant_settings(monkeypatch):
    for target in ("app.services.hostnames.get_settings", "app.api.hostnames.get_settings"):
        monkeypatch.setattr(target, lambda: SETTINGS)


def _holding(client, db_session, email: str, handle: str) -> dict:
    create_user(client, email, claim_handle=False)
    user = db_session.exec(select(UserORM).where(UserORM.email == email)).one()
    user.handle = handle
    db_session.add(user)
    db_session.commit()
    return {"X-Auth-Request-Email": email}


def test_the_check_requires_authentication(db_session, tenant_settings):
    from fastapi.testclient import TestClient

    from app.db import get_session
    from app.main import app as fastapi_app

    fastapi_app.dependency_overrides[get_session] = lambda: (yield db_session)
    with TestClient(fastapi_app) as no_auth_client:
        resp = no_auth_client.get("/api/hostnames/photos")
    fastapi_app.dependency_overrides.clear()

    assert resp.status_code == 404, resp.text


def test_a_bare_label_is_completed_and_checked(client, db_session, tenant_settings):
    headers = _holding(client, db_session, USER_EMAIL, "alice")

    resp = client.get("/api/hostnames/photos", headers=headers)

    assert resp.json() == {"fqdn": "photos-alice.freepod.app", "usable": True, "reason": None}


def test_mixed_case_is_normalized(client, db_session, tenant_settings):
    headers = _holding(client, db_session, USER_EMAIL, "alice")

    resp = client.get("/api/hostnames/Photos", headers=headers)

    assert resp.json()["fqdn"] == "photos-alice.freepod.app"


def test_the_callers_own_fqdn(client, db_session, tenant_settings):
    headers = _holding(client, db_session, USER_EMAIL, "alice")

    resp = client.get("/api/hostnames/photos-alice.freepod.app", headers=headers)

    assert resp.json() == {"fqdn": "photos-alice.freepod.app", "usable": True, "reason": None}


def test_a_name_ending_in_another_handle_is_claimed(client, db_session, tenant_settings):
    headers = _holding(client, db_session, OTHER_EMAIL, "bob")

    resp = client.get("/api/hostnames/photos-alice.freepod.app", headers=headers)

    assert resp.json() == {"fqdn": "photos-alice.freepod.app", "usable": False, "reason": "claimed"}


def test_an_application_name_in_use(client, db_session, tenant_settings, seed_parents):
    headers = _holding(client, db_session, USER_EMAIL, "alice")
    make_deployment_with_release(
        db_session,
        user_id=seed_parents["user_id"],
        desired_template_id=seed_parents["template_id"],
        hostname="photos-alice.freepod.app",
        status="ready",
        name="photos-in-use",
        namespace="photos-in-use",
    )
    db_session.commit()

    resp = client.get("/api/hostnames/photos", headers=headers)

    assert resp.json()["reason"] == "in_use"


def test_a_bare_label_without_a_handle_is_invalid(client, tenant_settings):
    create_user(client, USER_EMAIL, claim_handle=False)

    resp = client.get("/api/hostnames/photos", headers={"X-Auth-Request-Email": USER_EMAIL})

    assert resp.json() == {"fqdn": "photos", "usable": False, "reason": "invalid"}


def test_a_name_under_a_platform_domain_is_reserved(client, db_session, tenant_settings):
    headers = _holding(client, db_session, USER_EMAIL, "alice")

    resp = client.get("/api/hostnames/smtp.freepod.eu", headers=headers)

    assert resp.json()["reason"] == "reserved"


def test_handles_are_not_answered_here(client, db_session, tenant_settings):
    """A single label under the tenant domain is not a handle question any more."""
    headers = _holding(client, db_session, USER_EMAIL, "alice")

    resp = client.get("/api/hostnames/bob.freepod.app", headers=headers)

    assert resp.json()["reason"] == "invalid"
