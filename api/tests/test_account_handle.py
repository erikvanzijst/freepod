"""The handle an account holds: the column's guarantees, and the claim."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.config import CaelusSettings
from app.models import UserORM
from tests.conftest import OTHER_EMAIL, USER_EMAIL, create_user


def test_new_user_holds_no_handle(db_session):
    user = UserORM(email="nobody@example.com")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    assert user.handle is None


def test_two_accounts_cannot_hold_one_handle(db_session):
    db_session.add(UserORM(email="first@example.com", handle="ada"))
    db_session.commit()

    db_session.add(UserORM(email="second@example.com", handle="ada"))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_case_does_not_create_a_second_handle_in_the_database(db_session):
    db_session.add(UserORM(email="first@example.com", handle="ada"))
    db_session.commit()

    db_session.add(UserORM(email="second@example.com", handle="ADA"))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_a_deleted_account_keeps_its_handle_in_the_database(db_session):
    """The index only scopes uniqueness to live rows; refusing to re-issue a
    dead account's handle is the claim service's job (see below)."""
    gone = UserORM(email="gone@example.com", handle="ada", deleted_at=datetime.now(UTC))
    db_session.add(gone)
    db_session.commit()
    db_session.refresh(gone)

    assert gone.handle == "ada"


def test_many_accounts_may_hold_none(db_session):
    db_session.add(UserORM(email="n1@example.com"))
    db_session.add(UserORM(email="n2@example.com"))
    db_session.commit()


# --- The claim ---------------------------------------------------------------


def _headers(email: str) -> dict:
    return {"X-Auth-Request-Email": email}


def _claim(client, email: str, handle: str, *, dry_run: bool = False):
    path = "/api/me/handle?dry_run=1" if dry_run else "/api/me/handle"
    return client.post(path, json={"handle": handle}, headers=_headers(email))


def _held(client, email: str):
    return client.get("/api/me/handle", headers=_headers(email)).json()["handle"]


@pytest.fixture
def handle_settings(monkeypatch):
    """Point the claim at a known tenant domain and reserved list."""

    def _apply(reserved: list[str] | None = None) -> None:
        monkeypatch.setattr(
            "app.services.users.get_settings",
            lambda: CaelusSettings(
                tenant_domain="freepod.app", reserved_handles=reserved or [], _env_file=None
            ),
        )

    _apply()
    return _apply


def test_a_first_claim_is_accepted(client, handle_settings):
    create_user(client, USER_EMAIL, claim_handle=False)

    resp = _claim(client, USER_EMAIL, "adalovelace")

    assert resp.status_code == 200
    assert resp.json() == {
        "handle": "adalovelace",
        "suffix": "-adalovelace.freepod.app",
        "domain": "freepod.app",
    }
    assert _held(client, USER_EMAIL) == "adalovelace"


def test_a_claim_is_normalized_to_lowercase(client, handle_settings):
    create_user(client, USER_EMAIL, claim_handle=False)

    resp = _claim(client, USER_EMAIL, "AdaLovelace")

    assert resp.status_code == 200
    assert resp.json()["handle"] == "adalovelace"


def test_case_does_not_create_a_second_handle(client, handle_settings):
    create_user(client, USER_EMAIL, claim_handle=False)
    create_user(client, OTHER_EMAIL, claim_handle=False)
    assert _claim(client, USER_EMAIL, "Alice").status_code == 200

    resp = _claim(client, OTHER_EMAIL, "alice")

    assert resp.status_code == 409
    assert resp.json()["code"] == "handle_taken"
    assert _held(client, USER_EMAIL) == "alice"


@pytest.mark.parametrize(
    "candidate",
    ["ada-lovelace", "ada.lovelace", "ada_lovelace", "Ada Lovelace", "a", "a" * 21, ""],
)
def test_a_malformed_handle_is_refused(client, handle_settings, candidate):
    create_user(client, USER_EMAIL, claim_handle=False)

    resp = _claim(client, USER_EMAIL, candidate)

    assert resp.status_code == 400
    assert resp.json()["code"] == "handle_invalid"
    assert _held(client, USER_EMAIL) is None


@pytest.mark.parametrize("candidate", ["ab", "a" * 20, "ada1815"])
def test_well_formed_handles_are_accepted(client, handle_settings, candidate):
    create_user(client, USER_EMAIL, claim_handle=False)

    assert _claim(client, USER_EMAIL, candidate).status_code == 200


def test_a_reserved_handle_is_refused(client, handle_settings):
    handle_settings(reserved=["www", "freepod"])
    create_user(client, USER_EMAIL, claim_handle=False)

    resp = _claim(client, USER_EMAIL, "www")

    assert resp.status_code == 400
    assert resp.json()["code"] == "handle_reserved"


def test_a_handle_another_account_holds_is_refused(client, handle_settings):
    create_user(client, USER_EMAIL, claim_handle=False)
    create_user(client, OTHER_EMAIL, claim_handle=False)
    assert _claim(client, USER_EMAIL, "ada").status_code == 200

    resp = _claim(client, OTHER_EMAIL, "ADA")

    assert resp.status_code == 409
    assert resp.json()["code"] == "handle_taken"


def test_a_different_handle_is_refused(client, handle_settings):
    create_user(client, USER_EMAIL, claim_handle=False)
    _claim(client, USER_EMAIL, "ada")

    resp = _claim(client, USER_EMAIL, "grace")

    assert resp.status_code == 409
    assert resp.json()["code"] == "handle_already_claimed"
    assert _held(client, USER_EMAIL) == "ada"


def test_re_claiming_the_held_handle_is_idempotent(client, db_session, handle_settings):
    create_user(client, USER_EMAIL, claim_handle=False)
    _claim(client, USER_EMAIL, "ada")

    resp = _claim(client, USER_EMAIL, "Ada")

    assert resp.status_code == 200
    assert resp.json()["handle"] == "ada"
    assert _held(client, USER_EMAIL) == "ada"


def test_a_deleted_accounts_handle_stays_unclaimable(client, db_session, handle_settings):
    """The partial index stops constraining a deleted row, so the claim service
    is what keeps the handle held."""
    db_session.add(UserORM(email="gone@example.com", handle="ada", deleted_at=datetime.now(UTC)))
    db_session.commit()

    create_user(client, USER_EMAIL, claim_handle=False)
    resp = _claim(client, USER_EMAIL, "ada")

    assert resp.status_code == 409
    assert resp.json()["code"] == "handle_taken"


# --- The dry run -------------------------------------------------------------


def test_a_dry_run_answers_as_the_claim_and_stores_nothing(client, handle_settings):
    create_user(client, USER_EMAIL, claim_handle=False)

    resp = _claim(client, USER_EMAIL, "adalovelace", dry_run=True)

    assert resp.status_code == 200
    assert resp.json() == {
        "handle": "adalovelace",
        "suffix": "-adalovelace.freepod.app",
        "domain": "freepod.app",
    }
    assert _held(client, USER_EMAIL) is None


@pytest.mark.parametrize(
    ("setup", "candidate", "status", "code"),
    [
        (None, "ada-lovelace", 400, "handle_invalid"),
        ("reserved", "www", 400, "handle_reserved"),
        ("held", "ada", 409, "handle_taken"),
    ],
)
def test_a_dry_run_refuses_as_the_claim_would(
    client, handle_settings, setup, candidate, status, code
):
    if setup == "reserved":
        handle_settings(reserved=["www"])
    if setup == "held":
        create_user(client, OTHER_EMAIL, claim_handle=False)
        _claim(client, OTHER_EMAIL, "ada")
    create_user(client, USER_EMAIL, claim_handle=False)

    dry = _claim(client, USER_EMAIL, candidate, dry_run=True)
    real = _claim(client, USER_EMAIL, candidate)

    assert (dry.status_code, dry.json()["code"]) == (status, code)
    assert (real.status_code, real.json()["code"]) == (status, code)


def test_a_dry_run_of_the_held_handle(client, handle_settings):
    create_user(client, USER_EMAIL, claim_handle=False)
    _claim(client, USER_EMAIL, "alice")

    assert _claim(client, USER_EMAIL, "alice", dry_run=True).status_code == 200


def test_a_dry_run_reserves_nothing(client, handle_settings):
    create_user(client, USER_EMAIL, claim_handle=False)
    create_user(client, OTHER_EMAIL, claim_handle=False)

    assert _claim(client, USER_EMAIL, "ada", dry_run=True).status_code == 200
    assert _claim(client, OTHER_EMAIL, "ada", dry_run=True).status_code == 200
    assert _claim(client, OTHER_EMAIL, "ada").status_code == 200


# --- The read ----------------------------------------------------------------


def test_an_unclaimed_account_reports_no_handle(client, handle_settings):
    create_user(client, USER_EMAIL, claim_handle=False)

    resp = client.get("/api/me/handle", headers=_headers(USER_EMAIL))

    assert resp.status_code == 200
    assert resp.json() == {"handle": None, "suffix": None, "domain": "freepod.app"}


def test_a_claimed_account_reports_its_suffix(client, handle_settings):
    create_user(client, USER_EMAIL, claim_handle=False)
    _claim(client, USER_EMAIL, "adalovelace")

    resp = client.get("/api/me/handle", headers=_headers(USER_EMAIL))

    assert resp.json() == {
        "handle": "adalovelace",
        "suffix": "-adalovelace.freepod.app",
        "domain": "freepod.app",
    }


def test_the_claim_body_rejects_unknown_fields(client, handle_settings):
    create_user(client, USER_EMAIL, claim_handle=False)

    resp = client.post(
        "/api/me/handle", json={"handle": "ada", "user_id": 1}, headers=_headers(USER_EMAIL)
    )

    assert resp.status_code == 422


def test_the_user_record_reports_the_handle(client, db_session, handle_settings):
    db_session.add(UserORM(email="ada@example.com", handle="ada"))
    db_session.add(UserORM(email="none@example.com"))
    db_session.commit()

    by_email = {u["email"]: u for u in client.get("/api/users").json()}

    assert by_email["ada@example.com"]["handle"] == "ada"
    assert by_email["none@example.com"]["handle"] is None
    assert "wildcard_domain" not in by_email["ada@example.com"]


# --- Nothing releases one ----------------------------------------------------


def test_no_route_changes_or_releases_a_handle():
    from app.main import app

    writes = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
        if ("handle" in path or "subdomain" in path) and method != "get"
    }

    assert writes == {("POST", "/api/me/handle")}


def test_the_user_schemas_expose_no_writable_handle():
    from app.models import UserCreate

    assert "handle" not in UserCreate.model_fields


def test_the_operator_cli_only_claims():
    from app.cli import app as cli_app

    names = {command.name for command in cli_app.registered_commands}

    assert "claim-handle" in names
    assert not {n for n in names if n and "handle" in n} - {"claim-handle"}
