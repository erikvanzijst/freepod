"""Hostname validation after the namespace split: one label under a wildcard
domain is an account, two are one of its applications."""

import pytest
from sqlmodel import select

from app.config import CaelusSettings
from app.models import UserORM
from app.services.errors import HostnameException
from app.services.hostnames import (
    require_owned_subdomain,
    require_valid_hostname_for_deployment,
    require_valid_subdomain,
)
from tests.conftest import OTHER_EMAIL, USER_EMAIL, create_user, subject_for

SETTINGS = CaelusSettings(
    domain="",
    wildcard_domains=["freepod.eu"],
    reserved_hostnames=["www.freepod.eu"],
    _env_file=None,
)


def _reason(fn, *args, **kwargs) -> str:
    with pytest.raises(HostnameException) as excinfo:
        fn(*args, **kwargs)
    return excinfo.value.reason


# --- Depth ------------------------------------------------------------------

def test_two_labels_under_a_wildcard_domain_pass(db_session):
    require_valid_hostname_for_deployment(
        db_session, "photos.alice.freepod.eu", settings=SETTINGS
    )


@pytest.mark.parametrize(
    "fqdn",
    ["alice.freepod.eu", "a.b.alice.freepod.eu", "freepod.eu"],
)
def test_the_wrong_depth_is_invalid(db_session, fqdn):
    assert _reason(
        require_valid_hostname_for_deployment, db_session, fqdn, settings=SETTINGS
    ) == "invalid"


def test_the_depth_check_is_case_insensitive(db_session):
    require_valid_hostname_for_deployment(
        db_session, "Photos.Alice.Freepod.Eu", settings=SETTINGS
    )


def test_a_custom_domain_skips_the_depth_check(db_session):
    require_valid_hostname_for_deployment(
        db_session, "foo.bar.example.com", settings=SETTINGS
    )


def test_the_wrong_depth_short_circuits_before_reserved(db_session):
    """`www.freepod.eu` is both reserved and at the account depth; depth runs
    first, so it never reaches the reserved list."""
    assert _reason(
        require_valid_hostname_for_deployment,
        db_session,
        "www.freepod.eu",
        settings=SETTINGS,
    ) == "invalid"


# --- The subdomain question -------------------------------------------------

def test_a_free_label_is_available(db_session):
    require_valid_subdomain(db_session, "alice", settings=SETTINGS)


def test_a_held_label_is_claimed(db_session):
    db_session.add(UserORM(email="alice@example.com", subdomain="alice"))
    db_session.commit()

    assert _reason(require_valid_subdomain, db_session, "alice", settings=SETTINGS) == "claimed"


def test_a_soft_deleted_holder_still_holds(db_session):
    from datetime import UTC, datetime

    db_session.add(
        UserORM(email="alice@example.com", subdomain="alice", deleted_at=datetime.now(UTC))
    )
    db_session.commit()

    assert _reason(require_valid_subdomain, db_session, "alice", settings=SETTINGS) == "claimed"


def test_a_reserved_label_is_reserved(db_session):
    assert _reason(require_valid_subdomain, db_session, "www", settings=SETTINGS) == "reserved"


# --- Ownership ---------------------------------------------------------------

def test_an_application_under_the_owners_subdomain_is_allowed():
    require_owned_subdomain(
        "photos.alice.freepod.eu", subdomain="alice", settings=SETTINGS
    )


def test_an_application_under_another_subdomain_is_claimed():
    assert _reason(
        require_owned_subdomain,
        "photos.alice.freepod.eu",
        subdomain="bob",
        settings=SETTINGS,
    ) == "claimed"


def test_an_account_holding_none_owns_no_namespace():
    assert _reason(
        require_owned_subdomain,
        "photos.alice.freepod.eu",
        subdomain=None,
        settings=SETTINGS,
    ) == "claimed"


def test_a_custom_domain_is_not_owned_by_anyone():
    require_owned_subdomain("photos.example.com", subdomain="bob", settings=SETTINGS)


# --- The endpoint ------------------------------------------------------------

@pytest.fixture
def wildcard_settings(monkeypatch):
    for target in ("app.services.hostnames.get_settings", "app.api.hostnames.get_settings"):
        monkeypatch.setattr(target, lambda: SETTINGS)


def test_the_check_requires_authentication(db_session, wildcard_settings):
    from fastapi.testclient import TestClient

    from app.db import get_session
    from app.main import app as fastapi_app

    fastapi_app.dependency_overrides[get_session] = lambda: (yield db_session)
    with TestClient(fastapi_app) as no_auth_client:
        resp = no_auth_client.get("/api/hostnames/photos.alice.freepod.eu")
    fastapi_app.dependency_overrides.clear()

    assert resp.status_code == 404, resp.text


def test_a_single_label_is_answered_as_a_subdomain(client, wildcard_settings):
    create_user(client, USER_EMAIL)

    resp = client.get(
        "/api/hostnames/alice.freepod.eu", headers={"X-Auth-Request-Email": USER_EMAIL, "X-Auth-Request-User": subject_for(USER_EMAIL)}
    )

    assert resp.json() == {"fqdn": "alice.freepod.eu", "usable": True, "reason": None}


def test_a_claimed_label_reports_claimed(client, db_session, wildcard_settings):
    db_session.add(UserORM(email="alice@example.com", subdomain="alice"))
    db_session.commit()
    create_user(client, USER_EMAIL)

    resp = client.get(
        "/api/hostnames/alice.freepod.eu", headers={"X-Auth-Request-Email": USER_EMAIL, "X-Auth-Request-User": subject_for(USER_EMAIL)}
    )

    assert resp.json()["reason"] == "claimed"


def test_an_application_under_the_callers_own_subdomain_is_usable(
    client, db_session, wildcard_settings
):
    create_user(client, USER_EMAIL)
    holder = db_session.exec(select(UserORM).where(UserORM.email == USER_EMAIL)).one()
    holder.subdomain = "alice"
    db_session.add(holder)
    db_session.commit()

    resp = client.get(
        "/api/hostnames/photos.alice.freepod.eu",
        headers={"X-Auth-Request-Email": USER_EMAIL, "X-Auth-Request-User": subject_for(USER_EMAIL)},
    )

    assert resp.json()["usable"] is True


def test_an_application_under_another_account_reports_claimed(
    client, db_session, wildcard_settings
):
    db_session.add(UserORM(email="alice@example.com", subdomain="alice"))
    db_session.commit()
    create_user(client, OTHER_EMAIL)

    resp = client.get(
        "/api/hostnames/photos.alice.freepod.eu",
        headers={"X-Auth-Request-Email": OTHER_EMAIL, "X-Auth-Request-User": subject_for(OTHER_EMAIL)},
    )

    assert resp.json() == {
        "fqdn": "photos.alice.freepod.eu",
        "usable": False,
        "reason": "claimed",
    }
