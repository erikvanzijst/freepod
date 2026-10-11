"""The caller-identity resolution ladder.

`get_current_user` resolves an authenticated request to a user record by the
Keycloak subject, adopting pre-existing records by verified email and updating
a record's email in place when it changes. These tests drive the dependency
directly against a clean session so each branch of the ladder is exercised in
isolation, plus a couple of API-level checks for `get_optional_user` and the
D7 conflict's wire shape.

Spec: openspec/specs/caller-identity-resolution/spec.md.
"""

import pytest
from sqlmodel import select

from app.deps import get_current_user, get_optional_user
from app.models import (
    DeploymentORM,
    ProductORM,
    ProductTemplateVersionORM,
    ProductVisibility,
    SshKeyORM,
    UserORM,
)
from app.models.core import _utcnow
from app.services.errors import UserResolutionConflictException
from tests.conftest import CURRENT_TOS_VERSION, make_deployment_with_release


def _add_user(session, email, subject=None, **kwargs) -> UserORM:
    user = UserORM(email=email, keycloak_subject=subject, **kwargs)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _count_active_records(session) -> int:
    return len(session.exec(select(UserORM).where(UserORM.deleted_at.is_(None))).all())


# ── 2.1: a returning caller resolves by subject ────────────────────────────


def test_returning_caller_resolves_by_subject(db_session):
    user = _add_user(db_session, "a@x.com", "SUBJ_A")
    resolved = get_current_user("a@x.com", "SUBJ_A", db_session)
    assert resolved.id == user.id
    # The email is not part of the match: a record carrying the subject is
    # reached by it alone.
    assert resolved.email == "a@x.com"


def test_subject_is_opaque(db_session):
    # A subject in any form Keycloak may issue is stored and compared verbatim;
    # nothing parses or validates its shape.
    user = _add_user(db_session, "a@x.com", "opaque:not-a-uuid")
    resolved = get_current_user("a@x.com", "opaque:not-a-uuid", db_session)
    assert resolved.id == user.id


# ── 2.2: the ladder — subject, adoptable email, create ─────────────────────


def test_bound_record_is_not_matched_by_email(db_session):
    # A record carrying a different subject is unreachable by email. The
    # presented email is held by that bound record, so falling through to
    # create collides (D7) rather than resolving to the bound record: the
    # bound record is neither returned nor mutated.
    stale = _add_user(db_session, "a@x.com", "SUBJ_A")
    with pytest.raises(UserResolutionConflictException):
        get_current_user("a@x.com", "SUBJ_B", db_session)
    db_session.refresh(stale)
    assert stale.email == "a@x.com"
    assert stale.keycloak_subject == "SUBJ_A"
    assert _count_active_records(db_session) == 1


def test_new_record_created_when_nothing_matches(db_session):
    resolved = get_current_user("new@x.com", "SUBJ_NEW", db_session)
    assert resolved.email == "new@x.com"
    assert resolved.keycloak_subject == "SUBJ_NEW"
    assert _count_active_records(db_session) == 1


def test_new_record_created_despite_other_bound_record(db_session):
    # A bound record with a different subject neither matches by email nor
    # blocks creating a fresh record for a free address.
    _add_user(db_session, "a@x.com", "SUBJ_A")
    resolved = get_current_user("b@x.com", "SUBJ_B", db_session)
    assert resolved.email == "b@x.com"
    assert resolved.keycloak_subject == "SUBJ_B"
    assert _count_active_records(db_session) == 2


# ── 2.3: adoption stamps the subject ───────────────────────────────────────


def test_preexisting_record_adopted_on_first_request(db_session):
    record = _add_user(db_session, "a@x.com", None)
    resolved = get_current_user("a@x.com", "SUBJ_A", db_session)
    assert resolved.id == record.id
    assert resolved.keycloak_subject == "SUBJ_A"


def test_adopted_record_reached_by_subject_after_email_change(db_session):
    # A record adopted (subject stamped) is thereafter reached by subject
    # alone, even after its owner changes their address.
    record = _add_user(db_session, "a@x.com", None)
    get_current_user("a@x.com", "SUBJ_A", db_session)
    resolved = get_current_user("changed@x.com", "SUBJ_A", db_session)
    assert resolved.id == record.id
    assert resolved.email == "changed@x.com"


# ── 2.4: a changed email updates the record in place ───────────────────────


def _user_with_ownership(session, email, subject) -> UserORM:
    user = _add_user(
        session,
        email,
        subject,
        tos_accepted_version=CURRENT_TOS_VERSION,
        tos_accepted_at=_utcnow(),
    )
    product = ProductORM(name="ownership-product", visibility=ProductVisibility.PUBLIC)
    session.add(product)
    session.commit()
    session.refresh(product)
    template = ProductTemplateVersionORM(
        chart_ref="oci://example/ownership", chart_version="1.0.0", product_id=product.id
    )
    session.add(template)
    session.commit()
    session.refresh(template)
    make_deployment_with_release(
        session,
        user_id=user.id,
        desired_template_id=template.id,
        name="ownership",
        namespace="ownership-ns",
        status="ready",
    )
    key = SshKeyORM(
        user_id=user.id,
        key_type="ed25519",
        public_key="ed25519 AAAA test",
        fingerprint="SHA256:AAAA",
        bits=256,
    )
    session.add(key)
    session.commit()
    return user


def test_email_change_updates_record_in_place(db_session):
    user = _user_with_ownership(db_session, "a@x.com", "SUBJ_A")
    resolved = get_current_user("changed@x.com", "SUBJ_A", db_session)
    # Same record, new address: everything the record owns stays attached.
    assert resolved.id == user.id
    assert resolved.email == "changed@x.com"
    assert resolved.tos_accepted_version == CURRENT_TOS_VERSION
    assert _count_active_records(db_session) == 1

    deployment = db_session.exec(select(DeploymentORM)).one()
    assert deployment.user_id == resolved.id
    key = db_session.exec(select(SshKeyORM)).one()
    assert key.user_id == resolved.id
    # The subscription hangs off the deployment, which is still this user's.
    assert deployment.subscription_id is not None


def test_no_second_record_created_by_email_change(db_session):
    user = _add_user(db_session, "a@x.com", "SUBJ_A")
    resolved = get_current_user("changed@x.com", "SUBJ_A", db_session)
    assert resolved.id == user.id
    assert _count_active_records(db_session) == 1


# ── 2.5: the D7 collision fails loudly ─────────────────────────────────────


def test_stale_record_email_conflict_fails_loudly(db_session):
    # A stale record still holds an address another identity now owns. Binding
    # the new identity to that address would leave two active records on one
    # address, so the request fails rather than mutating either row.
    stale = _add_user(db_session, "a@x.com", "SUBJ_A")
    with pytest.raises(UserResolutionConflictException) as excinfo:
        get_current_user("a@x.com", "SUBJ_B", db_session)
    assert excinfo.value.code == "user_resolution_conflict"
    db_session.refresh(stale)
    assert stale.email == "a@x.com"
    assert stale.keycloak_subject == "SUBJ_A"
    assert _count_active_records(db_session) == 1


# ── 2.6: a subject-less request resolves by email alone ────────────────────


def test_subjectless_resolves_by_email(db_session):
    record = _add_user(db_session, "a@x.com", None)
    resolved = get_current_user("a@x.com", None, db_session)
    assert resolved.id == record.id


def test_subjectless_creates_when_none_exists(db_session):
    resolved = get_current_user("fresh@x.com", None, db_session)
    assert resolved.email == "fresh@x.com"
    assert resolved.keycloak_subject is None


def test_subjectless_does_not_bind_a_record(db_session):
    # A subject-less request neither stamps a record that carries no subject...
    record = _add_user(db_session, "a@x.com", None)
    resolved = get_current_user("a@x.com", None, db_session)
    assert resolved.id == record.id
    assert resolved.keycloak_subject is None


def test_subjectless_does_not_unbind_a_record(db_session):
    # ...nor clear the subject on one that does.
    record = _add_user(db_session, "a@x.com", "SUBJ_A")
    resolved = get_current_user("a@x.com", None, db_session)
    assert resolved.id == record.id
    assert resolved.keycloak_subject == "SUBJ_A"


# ── 2.7: get_optional_user and GET /api/products ───────────────────────────


def test_get_optional_user_anonymous_returns_none(db_session):
    assert get_optional_user(None, None, db_session) is None


def test_get_optional_user_subject_bearing_resolves(db_session):
    user = _add_user(db_session, "a@x.com", "SUBJ_A")
    resolved = get_optional_user("a@x.com", "SUBJ_A", db_session)
    assert resolved is not None and resolved.id == user.id


def test_get_optional_user_subject_less_resolves(db_session):
    user = _add_user(db_session, "a@x.com", "SUBJ_A")
    resolved = get_optional_user("a@x.com", None, db_session)
    assert resolved is not None and resolved.id == user.id


def test_products_identical_for_all_three_request_kinds(db_session):
    # GET /api/products is public (get_optional_user): anonymous, subject-
    # bearing and subject-less requests all answer 200. A clean client (no
    # default headers) is used so the subject-less case sends no subject at
    # all rather than inheriting one.
    from starlette.testclient import TestClient

    from app.db import get_session
    from app.main import app as fastapi_app

    def override_get_db():
        yield db_session

    fastapi_app.dependency_overrides[get_session] = override_get_db
    try:
        with TestClient(fastapi_app) as c:
            assert c.get("/api/products").status_code == 200
            assert c.get(
                "/api/products",
                headers={"X-Auth-Request-Email": "a@x.com", "X-Auth-Request-User": "SUBJ_A"},
            ).status_code == 200
            assert c.get(
                "/api/products", headers={"X-Auth-Request-Email": "a@x.com"}
            ).status_code == 200
    finally:
        fastapi_app.dependency_overrides.clear()


# ── API-level: the D7 conflict's wire shape ────────────────────────────────


def test_d7_conflict_is_a_409_with_a_stable_code(client, db_session):
    _add_user(db_session, "stale@x.com", "SUBJ_A")
    resp = client.get(
        "/api/me",
        headers={"X-Auth-Request-Email": "stale@x.com", "X-Auth-Request-User": "SUBJ_B"},
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "user_resolution_conflict"
