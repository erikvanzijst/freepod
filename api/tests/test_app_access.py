"""The access list of `listed` deployments, through the API (app-access-list)."""

from __future__ import annotations

import threading
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from sqlalchemy import create_engine, event
from sqlalchemy.pool import NullPool
from sqlmodel import Session, select

from app.config import CaelusSettings
from app.models import (
    AppAccessEntryORM,
    AppAccessInvitationORM,
    DeploymentORM,
    ProductORM,
    ProductTemplateVersionORM,
    UserORM,
)
from app.models.core import _utcnow
from app.services import app_access
from tests.conftest import AUTH_HEADER, TEST_DATABASE_URL, USER_EMAIL, make_deployment_with_release

SIGNING_VECTOR = Path(__file__).parents[2] / "daemons/app-auth/testdata/signing-vector.pem"
# Shared with daemons/app-auth/oidc_test.go: apps find the key that signed a
# logout token in app-auth's JWKS by this kid.
SIGNING_VECTOR_KID = "DJzcmmKmm4e0t9MCNr3DAProsJzIcYZIsPIOvC76tl0"
ISSUER = "https://login.dev.freepod.eu"
LISTED = {"auth": {"enabled": True, "access": "listed"}}
IMMICH = {"auth": {"enabled": True, "protocol": "oidc", "access": "listed",
                   "oidc": {"redirectPaths": ["/auth/login"], "backchannelLogoutPath": "/api/oauth/backchannel-logout"}}}


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    settings = CaelusSettings(
        app_auth_oidc_issuer=ISSUER,
        app_auth_oidc_signing_keys=SIGNING_VECTOR.read_text(),
        access_invitations_per_day=100,
        _env_file=None,
    )
    monkeypatch.setattr("app.services.app_access.get_settings", lambda: settings)
    return settings


@pytest.fixture
def sent(monkeypatch):
    """Invitations, as the mailer would have sent them."""
    mails: list[dict] = []

    def send_email(**kwargs):
        mails.append(kwargs)
        return True

    monkeypatch.setattr("app.services.app_access.mailer.send_email", send_email)
    return mails


@pytest.fixture
def app_answers(monkeypatch):
    """Stand in for the app receiving logout tokens; set `.status` or `.error`."""

    class App:
        status = 200
        error: Exception | None = None
        posts: list[dict] = []

    app = App()
    app.posts = []

    def post(url, *, data, timeout, follow_redirects):
        app.posts.append({"url": url, "data": data, "timeout": timeout, "follow_redirects": follow_redirects})
        if app.error is not None:
            raise app.error
        return httpx.Response(app.status, request=httpx.Request("POST", url))

    monkeypatch.setattr("app.services.app_access.httpx.post", post)
    return app


def _owner(session: Session) -> UserORM:
    return session.exec(select(UserORM).where(UserORM.email == USER_EMAIL)).one()


def _deployment(session: Session, owner: UserORM, *, system: dict | None = None, user: dict | None = None,
                applied: bool = True, hostname: str | None = None) -> DeploymentORM:
    product = ProductORM(name=f"p-{uuid4().hex[:8]}", created_at=_utcnow())
    session.add(product)
    session.flush()
    template = ProductTemplateVersionORM(
        product_id=product.id, chart_ref="oci://example/chart", chart_version="1.0.0", system_values_json=system
    )
    session.add(template)
    session.flush()
    deployment = make_deployment_with_release(
        session,
        user_id=owner.id,
        desired_template_id=template.id,
        name=f"app-{uuid4().hex[:6]}",
        namespace=f"ns-{uuid4().hex[:8]}",
        status="ready",
        hostname=hostname or f"cloud-{uuid4().hex[:6]}.freepod.app",
        user_values_json=user or {},
    )
    session.flush()
    if applied:
        deployment.applied_release_id = deployment.desired_release_id
        deployment.applied_template_id = template.id
    session.commit()
    session.refresh(deployment)
    return deployment


def _url(deployment: DeploymentORM, suffix: str = "") -> str:
    return f"/api/users/{deployment.user_id}/deployments/{deployment.id}/access{suffix}"


def _entry(session: Session, deployment: DeploymentORM, email: str, subject: str | None = None) -> AppAccessEntryORM:
    entry = AppAccessEntryORM(deployment_id=deployment.id, email=email, subject=subject,
                              name="Ana" if subject else None, bound_at=_utcnow() if subject else None)
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


# ── The read model ───────────────────────────────────────────────────────


def _read_auth(c, deployment: DeploymentORM):
    return c.get(f"/api/users/{deployment.user_id}/deployments/{deployment.id}").json()["auth"]


def test_read_model_defaults(user_client, db_session):
    c, _ = user_client
    deployment = _deployment(db_session, _owner(db_session), user={"auth": {"enabled": True}})
    assert _read_auth(c, deployment) == {"enabled": True, "protocol": "header", "access": "anyone", "listed_count": None}


def test_read_model_counts_a_listed_deployments_entries(user_client, db_session):
    c, _ = user_client
    deployment = _deployment(db_session, _owner(db_session), system=LISTED)
    for email in ("a@example.com", "b@example.com", "c@example.com"):
        _entry(db_session, deployment, email)
    assert _read_auth(c, deployment) == {"enabled": True, "protocol": "header", "access": "listed", "listed_count": 3}


def test_read_model_without_a_serving_release(user_client, db_session):
    c, _ = user_client
    deployment = _deployment(db_session, _owner(db_session), system=LISTED, applied=False)
    assert _read_auth(c, deployment) is None


def test_read_model_without_auth(user_client, db_session):
    c, _ = user_client
    deployment = _deployment(db_session, _owner(db_session))
    assert _read_auth(c, deployment) == {"enabled": False, "protocol": "header", "access": "anyone", "listed_count": None}


def test_listing_counts_in_constant_statements(user_client, db_session, test_database):
    c, _ = user_client
    owner = _owner(db_session)

    def statements() -> int:
        seen: list[str] = []

        def record(conn, cursor, statement, *args):
            seen.append(statement)

        event.listen(test_database.engine, "before_cursor_execute", record)
        try:
            body = c.get(f"/api/users/{owner.id}/deployments").json()
        finally:
            event.remove(test_database.engine, "before_cursor_execute", record)
        assert all(d["auth"]["listed_count"] == 1 for d in body)
        return len(seen)

    for _ in range(2):
        _entry(db_session, _deployment(db_session, owner, system=LISTED), f"{uuid4().hex[:6]}@example.com")
    few = statements()
    for _ in range(4):
        _entry(db_session, _deployment(db_session, owner, system=LISTED), f"{uuid4().hex[:6]}@example.com")
    assert statements() == few


# ── Reading the list ─────────────────────────────────────────────────────


def test_owner_and_admin_read_the_list(user_client, db_session):
    c, _ = user_client
    deployment = _deployment(db_session, _owner(db_session), system=LISTED)
    _entry(db_session, deployment, "ana@example.com", subject="s-ana")
    _entry(db_session, deployment, "jules@example.org")
    for headers in ({}, AUTH_HEADER):
        r = c.get(_url(deployment), headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert (body["enabled"], body["protocol"], body["access"], body["owner_email"], body["limit"]) == (
            True, "header", "listed", USER_EMAIL, 500
        )
        assert [(e["email"], e["name"], e["bound_at"] is not None) for e in body["entries"]] == [
            ("ana@example.com", "Ana", True),
            ("jules@example.org", None, False),
        ]


def test_another_user_cannot_see_the_list(user_client, db_session):
    c, admin = user_client
    deployment = _deployment(db_session, admin, system=LISTED)
    assert c.get(_url(deployment)).status_code == 403
    assert c.post(_url(deployment), json={"email": "x@example.com"}).status_code == 403


def test_unknown_deployment(user_client, db_session):
    c, _ = user_client
    owner = _owner(db_session)
    assert c.get(f"/api/users/{owner.id}/deployments/{uuid4()}/access").status_code == 404


# ── Adding ───────────────────────────────────────────────────────────────


def test_owner_adds_someone(user_client, db_session, sent):
    c, _ = user_client
    deployment = _deployment(db_session, _owner(db_session), system=LISTED)
    r = c.post(_url(deployment), json={"email": " Ana@Example.com "})
    assert r.status_code == 201, r.text
    assert r.json()["email"] == "ana@example.com" and r.json()["bound_at"] is None
    assert [e.email for e in db_session.exec(select(AppAccessEntryORM)).all()] == ["ana@example.com"]
    assert len(sent) == 1


@pytest.mark.parametrize("email", ["ana@", "@example.com", "ana", "ana@example", "ana @example.com", "a@b@example.com"])
def test_not_an_address(user_client, db_session, email):
    c, _ = user_client
    deployment = _deployment(db_session, _owner(db_session), system=LISTED)
    r = c.post(_url(deployment), json={"email": email})
    assert r.status_code == 422 and r.json()["code"] == "access_invalid_email"


@pytest.mark.parametrize("email", ["ana@example.com", "Ana@Example.com"])
def test_duplicate_in_any_case(user_client, db_session, email):
    c, _ = user_client
    deployment = _deployment(db_session, _owner(db_session), system=LISTED)
    _entry(db_session, deployment, "ana@example.com")
    r = c.post(_url(deployment), json={"email": email})
    assert r.status_code == 409 and r.json()["code"] == "access_duplicate"


def test_adding_the_owner_is_a_duplicate(user_client, db_session):
    c, _ = user_client
    deployment = _deployment(db_session, _owner(db_session), system=LISTED)
    r = c.post(_url(deployment), json={"email": USER_EMAIL.upper()})
    assert r.status_code == 409 and r.json()["code"] == "access_duplicate"
    assert db_session.exec(select(AppAccessEntryORM)).all() == []


def test_full_list(user_client, db_session, monkeypatch):
    c, _ = user_client
    monkeypatch.setattr(app_access, "ACCESS_LIST_LIMIT", 3)
    deployment = _deployment(db_session, _owner(db_session), system=LISTED)
    for i in range(3):
        _entry(db_session, deployment, f"p{i}@example.com")
    r = c.post(_url(deployment), json={"email": "more@example.com"})
    assert r.status_code == 409 and r.json()["code"] == "access_list_full"


@pytest.mark.parametrize(
    "values",
    [{"system": {"auth": {"enabled": True}}}, {"system": None}, {"system": LISTED, "applied": False},
     {"system": LISTED, "user": {"auth": {"access": "anyone"}}}],
    ids=["anyone", "no auth", "nothing serving", "user value over the template's"],
)
def test_adding_only_while_listed(user_client, db_session, values):
    c, _ = user_client
    deployment = _deployment(db_session, _owner(db_session), **values)
    r = c.post(_url(deployment), json={"email": "ana@example.com"})
    assert r.status_code == 409 and r.json()["code"] == "access_not_listed"


def test_administrators_cannot_change_a_list(user_client, db_session):
    c, _ = user_client
    deployment = _deployment(db_session, _owner(db_session), system=LISTED)
    entry = _entry(db_session, deployment, "ana@example.com")
    assert c.post(_url(deployment), json={"email": "x@example.com"}, headers=AUTH_HEADER).status_code == 403
    assert c.delete(_url(deployment, f"/{entry.id}"), headers=AUTH_HEADER).status_code == 403
    assert len(db_session.exec(select(AppAccessEntryORM)).all()) == 1


def test_concurrent_additions_never_pass_the_bound(user_client, db_session, test_database, monkeypatch):
    monkeypatch.setattr(app_access, "ACCESS_LIST_LIMIT", 20)
    deployment_id = _deployment(db_session, _owner(db_session), system=LISTED).id
    outcomes: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(40, timeout=30)
    # A connection per thread, which the shared engine's pool would not give.
    engine = create_engine(TEST_DATABASE_URL, poolclass=NullPool)

    def add(i: int) -> None:
        with Session(engine) as session:
            deployment = session.get(DeploymentORM, deployment_id)
            barrier.wait()
            try:
                app_access.add_entry(session, deployment, f"p{i}@example.com")
                outcome = "added"
            except app_access.ConflictException as exc:
                outcome = exc.code
        with lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=add, args=(i,)) for i in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    engine.dispose()
    assert outcomes.count("added") == 20
    assert outcomes.count("access_list_full") == 20
    db_session.expire_all()
    assert len(db_session.exec(select(AppAccessEntryORM)).all()) == 20


# ── Invitations ──────────────────────────────────────────────────────────


def test_invitation_is_fixed_text(user_client, db_session, sent):
    c, _ = user_client
    deployment = _deployment(db_session, _owner(db_session), system=LISTED, hostname="cloud-yourname.freepod.app")
    c.post(_url(deployment), json={"email": "ana@example.com"})
    [mail] = sent
    assert mail["to"] == "ana@example.com"
    assert USER_EMAIL in mail["body"] and "https://cloud-yourname.freepod.app" in mail["body"]
    assert "ana@example.com" in mail["body"]


def test_relay_failure_keeps_the_entry(user_client, db_session, monkeypatch):
    c, _ = user_client
    monkeypatch.setattr("app.services.app_access.mailer.send_email", lambda **kw: False)
    deployment = _deployment(db_session, _owner(db_session), system=LISTED)
    assert c.post(_url(deployment), json={"email": "ana@example.com"}).status_code == 201
    assert len(db_session.exec(select(AppAccessEntryORM)).all()) == 1


def test_invitation_limit(user_client, db_session, sent, _settings):
    c, _ = user_client
    _settings.access_invitations_per_day = 3
    owner = _owner(db_session)
    first, second = _deployment(db_session, owner, system=LISTED), _deployment(db_session, owner, system=LISTED)
    for i, deployment in enumerate([first, first, second]):
        assert c.post(_url(deployment), json={"email": f"p{i}@example.com"}).status_code == 201
    r = c.post(_url(second), json={"email": "more@example.com"})
    assert r.status_code == 429 and r.json()["code"] == "access_invitation_limit"
    assert "UTC" in r.json()["detail"]
    assert len(sent) == 3


def test_removing_does_not_return_invitations(user_client, db_session, sent, _settings):
    c, _ = user_client
    _settings.access_invitations_per_day = 3
    deployment = _deployment(db_session, _owner(db_session), system=LISTED)
    for _ in range(3):
        entry = c.post(_url(deployment), json={"email": "ana@example.com"}).json()
        assert c.delete(_url(deployment, f"/{entry['id']}")).status_code == 204
    r = c.post(_url(deployment), json={"email": "noor@example.org"})
    assert r.status_code == 429


def test_invitations_older_than_a_day_do_not_count(user_client, db_session, sent, _settings):
    c, _ = user_client
    _settings.access_invitations_per_day = 1
    owner = _owner(db_session)
    db_session.add(AppAccessInvitationORM(user_id=owner.id, sent_at=_utcnow() - timedelta(hours=25)))
    db_session.commit()
    deployment = _deployment(db_session, owner, system=LISTED)
    assert c.post(_url(deployment), json={"email": "ana@example.com"}).status_code == 201


def test_sweep_forgets_week_old_invitations(db_session, user_client):
    owner = _owner(db_session)
    old = AppAccessInvitationORM(user_id=owner.id, sent_at=_utcnow() - timedelta(days=8))
    recent = AppAccessInvitationORM(user_id=owner.id, sent_at=_utcnow() - timedelta(days=6))
    db_session.add_all([old, recent])
    db_session.commit()
    assert app_access.sweep_invitations(db_session) == 1
    assert [i.id for i in db_session.exec(select(AppAccessInvitationORM)).all()] == [recent.id]


# ── Removing ─────────────────────────────────────────────────────────────


def test_owner_removes_an_entry(user_client, db_session, app_answers):
    c, _ = user_client
    deployment = _deployment(db_session, _owner(db_session), system=LISTED)
    entry = _entry(db_session, deployment, "ana@example.com", subject="s-ana")
    assert c.delete(_url(deployment, f"/{entry.id}")).status_code == 204
    assert db_session.exec(select(AppAccessEntryORM)).all() == []
    assert app_answers.posts == []


def test_removing_an_unknown_entry(user_client, db_session):
    c, admin = user_client
    deployment = _deployment(db_session, _owner(db_session), system=LISTED)
    other = _deployment(db_session, admin, system=LISTED)
    entry = _entry(db_session, other, "ana@example.com")
    assert c.delete(_url(deployment, f"/{uuid4()}")).status_code == 404
    assert c.delete(_url(deployment, f"/{entry.id}")).status_code == 404


def test_removing_works_in_any_mode(user_client, db_session):
    c, _ = user_client
    deployment = _deployment(db_session, _owner(db_session), system={"auth": {"enabled": True}})
    entry = _entry(db_session, deployment, "ana@example.com")
    assert c.delete(_url(deployment, f"/{entry.id}")).status_code == 204


def test_removal_signs_the_person_out_of_an_oidc_app(user_client, db_session, app_answers):
    c, _ = user_client
    deployment = _deployment(db_session, _owner(db_session), system=IMMICH, hostname="photos-erik.freepod.app")
    entry = _entry(db_session, deployment, "ana@example.com", subject="s-ana")
    assert c.delete(_url(deployment, f"/{entry.id}")).status_code == 204
    [post] = app_answers.posts
    assert post["url"] == "https://photos-erik.freepod.app/api/oauth/backchannel-logout"
    assert post["follow_redirects"] is False and post["timeout"] == 10
    claims = _verified(post["data"]["logout_token"], audience=str(deployment.id))
    assert claims["sub"] == "s-ana"
    assert db_session.exec(select(AppAccessEntryORM)).all() == []


@pytest.mark.parametrize(
    "answer",
    [{"status": 400}, {"status": 503}, {"status": 302}, {"error": httpx.ReadTimeout("slow")},
     {"error": httpx.ConnectError("refused")}],
    ids=["400", "503", "redirect", "timeout", "unreachable"],
)
def test_removal_fails_when_the_app_does_not_accept(user_client, db_session, app_answers, answer):
    c, _ = user_client
    for k, v in answer.items():
        setattr(app_answers, k, v)
    deployment = _deployment(db_session, _owner(db_session), system=IMMICH, hostname="photos-erik.freepod.app")
    entry = _entry(db_session, deployment, "ana@example.com", subject="s-ana")
    r = c.delete(_url(deployment, f"/{entry.id}"))
    assert r.status_code == 502 and r.json()["code"] == "access_logout_failed"
    assert "photos-erik.freepod.app" in r.json()["detail"]
    db_session.expire_all()
    assert len(db_session.exec(select(AppAccessEntryORM)).all()) == 1


@pytest.mark.parametrize(
    ("system", "subject"),
    [
        (IMMICH, None),
        ({"auth": {"enabled": True, "access": "listed",
                   "oidc": {"backchannelLogoutPath": "/api/oauth/backchannel-logout"}}}, "s-ana"),
        ({"auth": {"enabled": True, "protocol": "oidc", "access": "listed",
                   "oidc": {"redirectPaths": ["/auth/login"]}}}, "s-ana"),
        ({"auth": {"enabled": True, "protocol": "oidc", "access": "listed",
                   "oidc": {"backchannelLogoutPath": "@evil.example/logout"}}}, "s-ana"),
    ],
    ids=["unbound entry", "header app", "no logout path", "logout path off the host"],
)
def test_removal_sends_nothing(user_client, db_session, app_answers, system, subject):
    c, _ = user_client
    deployment = _deployment(db_session, _owner(db_session), system=system)
    entry = _entry(db_session, deployment, "ana@example.com", subject=subject)
    assert c.delete(_url(deployment, f"/{entry.id}")).status_code == 204
    assert app_answers.posts == []


def test_logout_path_from_user_values_is_ignored(user_client, db_session, app_answers):
    c, _ = user_client
    system = {"auth": {"enabled": True, "protocol": "oidc", "access": "listed",
                       "oidc": {"redirectPaths": ["/auth/login"]}}}
    user = {"auth": {"oidc": {"backchannelLogoutPath": "/collect"}}}
    deployment = _deployment(db_session, _owner(db_session), system=system, user=user)
    entry = _entry(db_session, deployment, "ana@example.com", subject="s-ana")
    assert c.delete(_url(deployment, f"/{entry.id}")).status_code == 204
    assert app_answers.posts == []


# ── Logout tokens ────────────────────────────────────────────────────────


def _verified(token: str, *, audience: str) -> dict:
    key = load_pem_private_key(SIGNING_VECTOR.read_bytes(), password=None).public_key()
    header = jwt.get_unverified_header(token)
    assert header["typ"] == "logout+jwt" and header["kid"] == SIGNING_VECTOR_KID and header["alg"] == "RS256"
    return jwt.decode(token, key, algorithms=["RS256"], audience=audience, issuer=ISSUER)


def test_logout_token_contents():
    deployment_id = uuid4()
    first = app_access.logout_token(deployment_id, "s-ana")
    claims = _verified(first, audience=str(deployment_id))
    assert claims["sub"] == "s-ana"
    assert claims["events"] == {"http://schemas.openid.net/event/backchannel-logout": {}}
    assert claims["exp"] - claims["iat"] == 120
    assert "nonce" not in claims and "sid" not in claims
    assert claims["jti"] != _verified(app_access.logout_token(deployment_id, "s-ana"), audience=str(deployment_id))["jti"]


def test_key_id_is_the_shared_vector():
    assert app_access.key_id(load_pem_private_key(SIGNING_VECTOR.read_bytes(), password=None)) == SIGNING_VECTOR_KID


def test_no_signing_key_fails_the_removal(user_client, db_session, app_answers, _settings):
    c, _ = user_client
    _settings.app_auth_oidc_signing_keys = ""
    deployment = _deployment(db_session, _owner(db_session), system=IMMICH)
    entry = _entry(db_session, deployment, "ana@example.com", subject="s-ana")
    assert c.delete(_url(deployment, f"/{entry.id}")).status_code == 502
    assert app_answers.posts == []


@pytest.mark.parametrize(
    ("path", "uri"),
    [
        ("/api/oauth/backchannel-logout", "https://wiki-alice.freepod.app/api/oauth/backchannel-logout"),
        ("@evil.example/logout", None),
        (".evil.example/logout", None),
        (":443@evil.example/logout", None),
        ("//evil.example/logout", None),
        ("/logout?next=/", None),
        ("/logout#x", None),
        ("/log\\out", None),
        ("/log\nout", None),
        ("logout", None),
        (["/logout"], None),
        (None, None),
    ],
)
def test_logout_uri_stays_on_the_host(path, uri):
    assert app_access.logout_uri("Wiki-Alice.freepod.app", path) == uri
