"""How a request resolves to a user record (caller-identity-resolution).

The subject is the join key: a bound record is reached by subject alone, an
unbound one is adopted by its email, and an unknown caller is created with
both. No write may leave two live records holding one address.
"""

from __future__ import annotations

from sqlalchemy import func
from sqlmodel import select

from app.models import DeploymentORM, SshKeyORM, SubscriptionORM, UserORM
from app.services import users as user_service
from tests.conftest import (
    CURRENT_TOS_VERSION,
    auth_header,
    client,  # noqa: F401
    db_session,  # noqa: F401
    make_bare_deployment,
    subject_for,
    subjectless_header,
)

ALICE = "alice@example.com"


def _me(client, headers):
    return client.get("/api/me", headers=headers)


def _live(db_session, email: str) -> list[UserORM]:
    db_session.expire_all()
    return db_session.exec(
        select(UserORM).where(func.lower(UserORM.email) == email, UserORM.deleted_at.is_(None))
    ).all()


def _user(db_session, email: str, subject: str | None = None) -> UserORM:
    user = UserORM(email=email, keycloak_subject=subject)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _reload(db_session, user: UserORM) -> UserORM:
    db_session.expire_all()
    return db_session.get(UserORM, user.id)


def _user_count(db_session) -> int:
    db_session.expire_all()
    return len(db_session.exec(select(UserORM)).all())


# ── 2.1 / 2.2: the ladder ────────────────────────────────────────────────


def test_a_bound_record_resolves_by_subject(client, db_session):
    alice = _user(db_session, ALICE, "kc-alice")

    resp = _me(client, auth_header(ALICE, "kc-alice"))

    assert resp.status_code == 200
    assert resp.json()["id"] == alice.id


def test_an_unbound_record_is_adopted_by_email(client, db_session):
    alice = _user(db_session, ALICE)

    resp = _me(client, auth_header(ALICE, "kc-alice"))

    assert resp.json()["id"] == alice.id
    assert _reload(db_session, alice).keycloak_subject == "kc-alice"


def test_an_unknown_caller_is_created_bound(client, db_session):
    resp = _me(client, auth_header(ALICE, "kc-alice"))

    assert resp.status_code == 200
    [alice] = _live(db_session, ALICE)
    assert alice.id == resp.json()["id"]
    assert alice.keycloak_subject == "kc-alice"


def test_a_bound_record_is_never_matched_by_email(client, db_session):
    alice = _user(db_session, ALICE, "kc-alice")
    before = _user_count(db_session)

    resp = _me(client, auth_header(ALICE, "kc-someone-else"))

    assert resp.status_code == 409
    assert "another Freepod account" in resp.json()["detail"]
    assert _user_count(db_session) == before
    assert _reload(db_session, alice).keycloak_subject == "kc-alice"


def test_the_subject_is_compared_exactly(client, db_session):
    _user(db_session, ALICE, "kc-Alice")

    assert _me(client, auth_header(ALICE, "kc-alice")).status_code == 409


def test_a_deleted_record_does_not_reserve_its_subject(client, db_session):
    gone = _user(db_session, ALICE, "kc-alice")
    user_service.delete_user(db_session, user_id=gone.id)

    resp = _me(client, auth_header(ALICE, "kc-alice"))

    assert resp.status_code == 200
    assert resp.json()["id"] != gone.id
    assert _reload(db_session, gone).keycloak_subject == "kc-alice"


# ── 2.3 / 2.4: an address change keeps the account ─────────────────────


def test_an_adopted_record_follows_its_owner_to_a_new_address(client, db_session):
    alice = _user(db_session, ALICE)
    _me(client, auth_header(ALICE, "kc-alice"))

    resp = _me(client, auth_header("alice@new.example", "kc-alice"))

    assert resp.json()["id"] == alice.id
    assert resp.json()["email"] == "alice@new.example"


def test_an_address_change_keeps_everything_the_record_owns(client, db_session, tmp_path):
    alice = _user(db_session, ALICE, "kc-alice")
    alice.tos_accepted_version = CURRENT_TOS_VERSION
    db_session.add(alice)
    db_session.commit()
    deployment = make_bare_deployment(db_session, alice.id)
    db_session.add(
        SshKeyORM(
            user_id=alice.id,
            key_type="ssh-ed25519",
            public_key="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFakeKeyForTheIdentityTest",
            fingerprint="SHA256:identity-test",
            bits=256,
        )
    )
    db_session.commit()

    resp = _me(client, auth_header("alice@new.example", "kc-alice"))

    assert resp.json()["id"] == alice.id
    db_session.expire_all()
    assert db_session.get(DeploymentORM, deployment.id).user_id == alice.id
    assert db_session.get(SubscriptionORM, deployment.subscription_id).user_id == alice.id
    assert db_session.exec(select(SshKeyORM).where(SshKeyORM.user_id == alice.id)).all()
    assert _reload(db_session, alice).tos_accepted_version == CURRENT_TOS_VERSION
    assert _live(db_session, ALICE) == []
    assert [u.id for u in _live(db_session, "alice@new.example")] == [alice.id]


def test_a_case_only_difference_is_not_an_address_change(client, db_session):
    alice = _user(db_session, "Alice@Example.com", "kc-alice")

    _me(client, auth_header(ALICE, "kc-alice"))

    assert _reload(db_session, alice).email == "Alice@Example.com"


# ── 2.5: an address another record still holds ─────────────────────────


def test_moving_to_an_address_an_unbound_record_holds_is_refused(client, db_session):
    alice = _user(db_session, ALICE, "kc-alice")
    stale = _user(db_session, "bob@example.com")

    resp = _me(client, auth_header("bob@example.com", "kc-alice"))

    assert resp.status_code == 409
    assert _reload(db_session, alice).email == ALICE
    assert _reload(db_session, stale).keycloak_subject is None


def test_moving_to_an_address_a_bound_record_holds_is_refused(client, db_session):
    alice = _user(db_session, ALICE, "kc-alice")
    bob = _user(db_session, "bob@example.com", "kc-bob")

    resp = _me(client, auth_header("bob@example.com", "kc-alice"))

    assert resp.status_code == 409
    assert _reload(db_session, alice).email == ALICE
    assert _reload(db_session, bob).email == "bob@example.com"


# ── 2.6: a request without a subject ───────────────────────────────────


def test_a_subjectless_request_resolves_by_email(client, db_session):
    alice = _user(db_session, ALICE)

    resp = _me(client, subjectless_header(ALICE))

    assert resp.json()["id"] == alice.id
    assert _reload(db_session, alice).keycloak_subject is None


def test_a_subjectless_request_reaches_a_bound_record_and_leaves_it_bound(client, db_session):
    alice = _user(db_session, ALICE, "kc-alice")

    resp = _me(client, subjectless_header(ALICE))

    assert resp.json()["id"] == alice.id
    assert _reload(db_session, alice).keycloak_subject == "kc-alice"


def test_a_subjectless_request_creates_an_unbound_record(client, db_session):
    resp = _me(client, subjectless_header(ALICE))

    [alice] = _live(db_session, ALICE)
    assert alice.id == resp.json()["id"]
    assert alice.keycloak_subject is None


# ── 2.7: endpoints that also serve anonymous visitors ──────────────────


def test_optional_identity_resolves_alike_with_or_without_a_subject(client, db_session):
    public = client.post(
        "/api/products", json={"name": "visible", "description": "d", "visibility": "public"}
    )
    hidden = client.post("/api/products", json={"name": "hidden", "description": "d"})
    assert public.status_code == hidden.status_code == 201

    def names(headers):
        resp = client.get("/api/products", headers=headers)
        assert resp.status_code == 200
        return sorted(p["name"] for p in resp.json())

    anonymous = names({"X-Auth-Request-Email": "", "X-Auth-Request-User": ""})
    assert anonymous == ["visible"]
    assert names(auth_header(ALICE)) == anonymous
    assert names(subjectless_header(ALICE)) == anonymous
    [alice] = _live(db_session, ALICE)
    assert alice.keycloak_subject == subject_for(ALICE)


def test_a_concurrent_first_request_is_resolved_not_failed(client, db_session, monkeypatch):
    """Two first requests race: the loser's write violates a unique index, and
    it resolves to the record the winner wrote."""
    from app import deps

    resolve = deps._resolve_user
    calls = []

    def racing(session, email, subject):
        if not calls:
            calls.append(1)
            _user(db_session, email, subject)
            session.add(UserORM(email=email, keycloak_subject=subject))
            session.commit()
        return resolve(session, email, subject)

    monkeypatch.setattr(deps, "_resolve_user", racing)

    resp = _me(client, auth_header(ALICE, "kc-alice"))

    assert resp.status_code == 200
    assert [u.id for u in _live(db_session, ALICE)] == [resp.json()["id"]]
