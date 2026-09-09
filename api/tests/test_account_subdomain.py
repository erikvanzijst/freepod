"""The subdomain an account holds: the column's guarantees, and the claim."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import UserORM


def test_new_user_holds_no_subdomain(db_session):
    user = UserORM(email="nobody@example.com")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    assert user.subdomain is None


def test_two_accounts_cannot_hold_one_label(db_session):
    db_session.add(UserORM(email="first@example.com", subdomain="ada"))
    db_session.commit()

    db_session.add(UserORM(email="second@example.com", subdomain="ada"))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_case_does_not_create_a_second_label(db_session):
    db_session.add(UserORM(email="first@example.com", subdomain="ada"))
    db_session.commit()

    db_session.add(UserORM(email="second@example.com", subdomain="ADA"))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_a_deleted_account_keeps_its_label(db_session):
    """The index is partial, so a deleted row does not constrain the column --
    but its label must stay held all the same. This asserts only the half the
    database owns; the claim service refuses the label (see the claim tests)."""
    from datetime import UTC, datetime

    gone = UserORM(email="gone@example.com", subdomain="ada", deleted_at=datetime.now(UTC))
    db_session.add(gone)
    db_session.commit()
    db_session.refresh(gone)

    assert gone.subdomain == "ada"


# --- The claim ---------------------------------------------------------------

from app.config import CaelusSettings
from tests.conftest import OTHER_EMAIL, USER_EMAIL, create_user, subject_for


def _headers(email: str) -> dict:
    return {"X-Auth-Request-Email": email, "X-Auth-Request-User": subject_for(email)}


@pytest.fixture
def hostname_settings(monkeypatch):
    """Point the subdomain checks at a known domain and reserved list."""

    def _apply(reserved: list[str] | None = None) -> None:
        monkeypatch.setattr(
            "app.services.hostnames.get_settings",
            lambda: CaelusSettings(
                domain="freepod.eu",
                wildcard_domains=["freepod.eu"],
                reserved_hostnames=reserved or [],
                _env_file=None,
            ),
        )
        monkeypatch.setattr(
            "app.services.users.get_settings",
            lambda: CaelusSettings(domain="freepod.eu", _env_file=None),
        )

    _apply()
    return _apply


def test_a_first_claim_is_accepted(client, hostname_settings):
    create_user(client, USER_EMAIL, claim_subdomain=False)

    resp = client.post(
        "/api/me/subdomain", json={"subdomain": "adalovelace"}, headers=_headers(USER_EMAIL)
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "subdomain": "adalovelace",
        "fqdn": "adalovelace.freepod.eu",
        "domain": "freepod.eu",
    }


def test_a_claim_is_normalized_to_lowercase(client, hostname_settings):
    create_user(client, USER_EMAIL, claim_subdomain=False)

    resp = client.post(
        "/api/me/subdomain", json={"subdomain": "AdaLovelace"}, headers=_headers(USER_EMAIL)
    )

    assert resp.status_code == 200
    assert resp.json()["subdomain"] == "adalovelace"


@pytest.mark.parametrize(
    "candidate",
    [
        "ada.lovelace",
        "-ada",
        "ada-",
        "Ada Lovelace",
        "a",
        "a" * 64,
        "ada_lovelace",
    ],
)
def test_a_malformed_candidate_is_refused(client, hostname_settings, candidate):
    create_user(client, USER_EMAIL, claim_subdomain=False)

    resp = client.post(
        "/api/me/subdomain", json={"subdomain": candidate}, headers=_headers(USER_EMAIL)
    )

    assert resp.status_code == 400
    assert resp.json()["code"] == "subdomain_invalid"

    held = client.get("/api/me/subdomain", headers=_headers(USER_EMAIL))
    assert held.json()["subdomain"] is None


def test_a_label_of_sixty_three_characters_is_accepted(client, hostname_settings):
    create_user(client, USER_EMAIL, claim_subdomain=False)

    resp = client.post(
        "/api/me/subdomain", json={"subdomain": "a" * 63}, headers=_headers(USER_EMAIL)
    )

    assert resp.status_code == 200


def test_a_reserved_label_is_refused(client, hostname_settings):
    hostname_settings(reserved=["www.freepod.eu"])
    create_user(client, USER_EMAIL, claim_subdomain=False)

    resp = client.post(
        "/api/me/subdomain", json={"subdomain": "www"}, headers=_headers(USER_EMAIL)
    )

    assert resp.status_code == 400
    assert resp.json()["code"] == "subdomain_reserved"


def test_reserving_a_hostname_reserves_its_label(client, hostname_settings):
    """One list, two roles: nothing else is touched to make a label unclaimable."""
    create_user(client, USER_EMAIL, claim_subdomain=False)
    free = client.post(
        "/api/me/subdomain", json={"subdomain": "grafana"}, headers=_headers(USER_EMAIL)
    )
    assert free.status_code == 200

    hostname_settings(reserved=["grafana.freepod.eu"])
    create_user(client, OTHER_EMAIL, claim_subdomain=False)
    resp = client.post(
        "/api/me/subdomain", json={"subdomain": "grafana"}, headers=_headers(OTHER_EMAIL)
    )

    assert resp.status_code == 400
    assert resp.json()["code"] == "subdomain_reserved"


def test_a_label_another_account_holds_is_refused(client, hostname_settings):
    create_user(client, USER_EMAIL, claim_subdomain=False)
    create_user(client, OTHER_EMAIL, claim_subdomain=False)
    assert client.post(
        "/api/me/subdomain", json={"subdomain": "ada"}, headers=_headers(USER_EMAIL)
    ).status_code == 200

    resp = client.post(
        "/api/me/subdomain", json={"subdomain": "ADA"}, headers=_headers(OTHER_EMAIL)
    )

    assert resp.status_code == 409
    assert resp.json()["code"] == "subdomain_taken"


def test_a_second_claim_is_refused(client, hostname_settings):
    create_user(client, USER_EMAIL, claim_subdomain=False)
    client.post("/api/me/subdomain", json={"subdomain": "ada"}, headers=_headers(USER_EMAIL))

    resp = client.post(
        "/api/me/subdomain", json={"subdomain": "grace"}, headers=_headers(USER_EMAIL)
    )

    assert resp.status_code == 409
    assert resp.json()["code"] == "subdomain_already_claimed"
    held = client.get("/api/me/subdomain", headers=_headers(USER_EMAIL))
    assert held.json()["subdomain"] == "ada"


def test_re_submitting_the_held_label_is_also_refused(client, hostname_settings):
    create_user(client, USER_EMAIL, claim_subdomain=False)
    client.post("/api/me/subdomain", json={"subdomain": "ada"}, headers=_headers(USER_EMAIL))

    resp = client.post(
        "/api/me/subdomain", json={"subdomain": "ada"}, headers=_headers(USER_EMAIL)
    )

    assert resp.status_code == 409
    assert resp.json()["code"] == "subdomain_already_claimed"


def test_a_deleted_accounts_label_stays_unclaimable(client, db_session, hostname_settings):
    """Task 1.3: the partial index stops constraining a deleted row, so the
    claim service is what keeps the label held."""
    from datetime import UTC, datetime

    gone = UserORM(email="gone@example.com", subdomain="ada", deleted_at=datetime.now(UTC))
    db_session.add(gone)
    db_session.commit()

    create_user(client, USER_EMAIL, claim_subdomain=False)
    resp = client.post(
        "/api/me/subdomain", json={"subdomain": "ada"}, headers=_headers(USER_EMAIL)
    )

    assert resp.status_code == 409
    assert resp.json()["code"] == "subdomain_taken"


# --- The read ----------------------------------------------------------------

def test_an_unclaimed_account_reports_no_subdomain(client, hostname_settings):
    create_user(client, USER_EMAIL, claim_subdomain=False)

    resp = client.get("/api/me/subdomain", headers=_headers(USER_EMAIL))

    assert resp.status_code == 200
    assert resp.json() == {"subdomain": None, "fqdn": None, "domain": "freepod.eu"}


def test_a_claimed_account_reports_its_fqdn(client, hostname_settings):
    create_user(client, USER_EMAIL, claim_subdomain=False)
    client.post(
        "/api/me/subdomain", json={"subdomain": "adalovelace"}, headers=_headers(USER_EMAIL)
    )

    resp = client.get("/api/me/subdomain", headers=_headers(USER_EMAIL))

    assert resp.json() == {
        "subdomain": "adalovelace",
        "fqdn": "adalovelace.freepod.eu",
        "domain": "freepod.eu",
    }


def test_the_claim_body_rejects_unknown_fields(client, hostname_settings):
    create_user(client, USER_EMAIL, claim_subdomain=False)

    resp = client.post(
        "/api/me/subdomain",
        json={"subdomain": "ada", "user_id": 1},
        headers=_headers(USER_EMAIL),
    )

    assert resp.status_code == 422


# --- Nothing releases one ----------------------------------------------------

def test_no_route_changes_or_releases_a_subdomain():
    """Task 2.5, for the API half: the only write is the claim itself."""
    from app.main import app

    writes = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
        if "subdomain" in getattr(route, "path", "") and method != "GET"
    }

    assert writes == {("POST", "/api/me/subdomain")}


def test_the_user_schemas_expose_no_writable_subdomain():
    """A subdomain must not ride in on any other resource's payload."""
    from app.models import UserCreate, UserRead

    assert "subdomain" not in UserCreate.model_fields
    assert "subdomain" not in UserRead.model_fields
