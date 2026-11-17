"""The GitHub connection: state, authorization, token refresh, and disconnecting."""

from __future__ import annotations

import base64
import json
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlmodel import select

from app.config import CaelusSettings
from app.models import GitConnectionORM
from app.models.core import _utcnow
from app.services import github
from app.services.errors import InvalidInputException
from tests.conftest import OTHER_EMAIL, USER_EMAIL, auth_header, create_user

CLIENT_ID = "Iv23litest"
CLIENT_SECRET = "s3cret"
BASE_URL = "https://freepod.test"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIVATE_PEM = _KEY.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()


class FakeGitHub:
    """GitHub's token endpoint and the few API calls the service makes."""

    def __init__(self) -> None:
        self.accounts = {"code-alice": {"id": 1001, "login": "alice"}}
        self.tokens: dict[str, dict] = {}
        self.issued = 0
        self.valid_refresh: set[str] = set()
        self.revoked: list[str] = []
        self.calls: list[str] = []
        self.refuse_refresh = False

    def _issue(self, account: dict) -> dict:
        self.issued += 1
        refresh = f"ghr_{self.issued}"
        self.valid_refresh.add(refresh)
        self.tokens[f"ghu_{self.issued}"] = account
        return {
            "access_token": f"ghu_{self.issued}",
            "expires_in": 28800,
            "refresh_token": refresh,
            "refresh_token_expires_in": 15897600,
            "token_type": "bearer",
            "scope": "",
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(f"{request.method} {request.url.path}")
        if request.url.path == "/login/oauth/access_token":
            form = parse_qs(request.content.decode())
            assert form["client_id"] == [CLIENT_ID] and form["client_secret"] == [CLIENT_SECRET]
            if "code" in form:
                account = self.accounts.get(form["code"][0])
                if account is None:
                    return httpx.Response(200, json={"error": "bad_verification_code"})
                assert form["redirect_uri"] == [f"{BASE_URL}/api/git/github/callback"]
                return httpx.Response(200, json=self._issue(account))
            refresh = form["refresh_token"][0]
            if self.refuse_refresh or refresh not in self.valid_refresh:
                return httpx.Response(200, json={"error": "bad_refresh_token"})
            self.valid_refresh.discard(refresh)
            return httpx.Response(200, json=self._issue({"id": 1001, "login": "alice"}))

        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        if request.url.path == "/user":
            return httpx.Response(200, json=self.tokens[token])
        if request.url.path == "/user/installations":
            return httpx.Response(
                200,
                json={
                    "total_count": 1,
                    "installations": [
                        {
                            "id": 77,
                            "account": {"login": "alice", "type": "User"},
                            "repository_selection": "selected",
                            "html_url": "https://github.com/settings/installations/77",
                        }
                    ],
                },
            )
        if request.method == "DELETE" and request.url.path == f"/applications/{CLIENT_ID}/grant":
            basic = base64.b64decode(request.headers["authorization"].removeprefix("Basic ")).decode()
            assert basic == f"{CLIENT_ID}:{CLIENT_SECRET}"
            self.revoked.append(json.loads(request.content)["access_token"])
            return httpx.Response(204)
        return httpx.Response(404)


@pytest.fixture
def fake_github(monkeypatch):
    fake = FakeGitHub()
    settings = CaelusSettings(
        github_app_id=1,
        github_app_slug="freepod-test",
        github_client_id=CLIENT_ID,
        github_client_secret=CLIENT_SECRET,
        github_private_key=PRIVATE_PEM,
        base_url=BASE_URL,
        _env_file=None,
    )
    monkeypatch.setattr(github, "get_settings", lambda: settings)
    monkeypatch.setattr("app.api.git.get_settings", lambda: settings)
    monkeypatch.setattr(
        github, "http_client", lambda: httpx.Client(transport=httpx.MockTransport(fake.handler))
    )
    return fake


def _connect(client, email: str, user_id: int, code: str = "code-alice"):
    start = client.post(f"/api/users/{user_id}/git/github/connect", headers=auth_header(email))
    assert start.status_code == 200, start.text
    state = parse_qs(urlparse(start.json()["authorize_url"]).query)["state"][0]
    return client.get(
        "/api/git/github/callback",
        params={"code": code, "state": state},
        headers=auth_header(email),
        follow_redirects=False,
    )


def _outcome(response) -> dict[str, list[str]]:
    assert response.status_code == 303
    location = urlparse(response.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == f"{BASE_URL}/settings/git"
    return parse_qs(location.query)


# ── State ─────────────────────────────────────────────────────────────


def test_state_round_trips_for_its_user(fake_github):
    cfg = github.config()
    github.verify_state(cfg, github.sign_state(cfg, 5), 5)


def _refused(state: str, user_id: int) -> str:
    with pytest.raises(InvalidInputException) as exc:
        github.verify_state(github.config(), state, user_id)
    return exc.value.code


def test_state_is_refused_for_another_account(fake_github):
    assert _refused(github.sign_state(github.config(), 5), 6) == "github_state_other_account"


def test_a_tampered_or_unsigned_state_is_refused(fake_github):
    payload, signature = github.sign_state(github.config(), 5).split(".")
    forged = github._b64(json.dumps({"u": "5", "e": 9999999999, "n": "x"}).encode())
    assert _refused(f"{forged}.{signature}", 5) == "github_state_invalid"
    assert _refused(payload, 5) == "github_state_invalid"


def test_state_expires(fake_github):
    cfg = github.config()
    state = github.sign_state(cfg, 5, now=_utcnow() - timedelta(hours=1))
    with pytest.raises(InvalidInputException) as exc:
        github.verify_state(cfg, state, 5)
    assert exc.value.code == "github_state_expired"


def test_app_jwt_is_signed_by_the_app_key(fake_github):
    token = github.app_jwt(github.config())
    claims = jwt.decode(token, _KEY.public_key(), algorithms=["RS256"])
    assert claims["iss"] == CLIENT_ID
    assert claims["exp"] - claims["iat"] == 600


# ── Connecting ────────────────────────────────────────────────────────


def test_connect_is_unavailable_without_an_app(client, monkeypatch):
    monkeypatch.setattr(github, "get_settings", lambda: CaelusSettings(_env_file=None))
    user = create_user(client, USER_EMAIL)
    response = client.post(
        f"/api/users/{user['id']}/git/github/connect", headers=auth_header(USER_EMAIL)
    )
    assert response.status_code == 503
    assert response.json()["code"] == "github_unavailable"


def test_connect_links_carry_the_callback_and_a_state(client, fake_github):
    user = create_user(client, USER_EMAIL)
    body = client.post(
        f"/api/users/{user['id']}/git/github/connect", headers=auth_header(USER_EMAIL)
    ).json()
    authorize = urlparse(body["authorize_url"])
    query = parse_qs(authorize.query)
    assert f"{authorize.netloc}{authorize.path}" == "github.com/login/oauth/authorize"
    assert query["client_id"] == [CLIENT_ID]
    assert query["redirect_uri"] == [f"{BASE_URL}/api/git/github/callback"]
    install = urlparse(body["install_url"])
    assert install.path == "/apps/freepod-test/installations/new"
    assert parse_qs(install.query)["state"] == query["state"]


def test_only_the_owner_may_start_connecting(client, fake_github):
    user = create_user(client, USER_EMAIL)
    response = client.post(f"/api/users/{user['id']}/git/github/connect")
    assert response.status_code == 403


def test_callback_stores_the_connection_encrypted(client, fake_github, db_session):
    user = create_user(client, USER_EMAIL)
    assert _outcome(_connect(client, USER_EMAIL, user["id"])) == {"github": ["connected"]}

    row = db_session.exec(select(GitConnectionORM)).one()
    assert (row.user_id, row.provider, row.host, row.account_id, row.login) == (
        user["id"], "github", "github.com", "1001", "alice"
    )
    assert "ghu_" not in row.tokens_encrypted and "ghr_" not in row.tokens_encrypted
    assert row.access_token_expires_at is not None and row.refresh_token_expires_at is not None

    listed = client.get(f"/api/users/{user['id']}/git", headers=auth_header(USER_EMAIL)).json()
    assert [(c["provider"], c["login"]) for c in listed] == [("github", "alice")]


def test_callback_refuses_a_state_started_by_another_account(client, fake_github, db_session):
    user = create_user(client, USER_EMAIL)
    create_user(client, OTHER_EMAIL)
    start = client.post(
        f"/api/users/{user['id']}/git/github/connect", headers=auth_header(USER_EMAIL)
    ).json()
    state = parse_qs(urlparse(start["authorize_url"]).query)["state"][0]
    response = client.get(
        "/api/git/github/callback",
        params={"code": "code-alice", "state": state},
        headers=auth_header(OTHER_EMAIL),
        follow_redirects=False,
    )
    assert _outcome(response) == {"github_error": ["github_state_other_account"]}
    assert db_session.exec(select(GitConnectionORM)).first() is None
    assert fake_github.calls == []


def test_callback_reports_a_refused_code(client, fake_github):
    user = create_user(client, USER_EMAIL)
    response = _connect(client, USER_EMAIL, user["id"], code="stale")
    assert _outcome(response) == {"github_error": ["github_code_invalid"]}


def test_a_github_account_connects_to_one_freepod_account(client, fake_github):
    first = create_user(client, USER_EMAIL)
    second = create_user(client, OTHER_EMAIL)
    _connect(client, USER_EMAIL, first["id"])
    response = _connect(client, OTHER_EMAIL, second["id"])
    assert _outcome(response) == {"github_error": ["github_account_in_use"]}


def test_reconnecting_replaces_the_tokens(client, fake_github, db_session):
    user = create_user(client, USER_EMAIL)
    _connect(client, USER_EMAIL, user["id"])
    _connect(client, USER_EMAIL, user["id"])
    assert len(db_session.exec(select(GitConnectionORM)).all()) == 1
    assert github.access_token(db_session, user["id"]) == "ghu_2"


def test_an_installation_request_without_a_code_is_reported(client, fake_github):
    create_user(client, USER_EMAIL)
    response = client.get(
        "/api/git/github/callback",
        params={"setup_action": "request"},
        headers=auth_header(USER_EMAIL),
        follow_redirects=False,
    )
    assert _outcome(response) == {"github": ["requested"]}


# ── Tokens ────────────────────────────────────────────────────────────


def _expire(db_session, *, refresh_too: bool = False) -> None:
    row = db_session.exec(select(GitConnectionORM)).one()
    past = _utcnow().replace(tzinfo=None) - timedelta(minutes=1)
    row.access_token_expires_at = past
    if refresh_too:
        row.refresh_token_expires_at = past
    db_session.add(row)
    db_session.commit()


def test_a_fresh_token_is_used_as_is(client, fake_github, db_session):
    user = create_user(client, USER_EMAIL)
    _connect(client, USER_EMAIL, user["id"])
    assert github.access_token(db_session, user["id"]) == "ghu_1"
    assert fake_github.issued == 1


def test_an_expiring_token_is_refreshed_once(client, fake_github, db_session):
    user = create_user(client, USER_EMAIL)
    _connect(client, USER_EMAIL, user["id"])
    _expire(db_session)
    assert github.access_token(db_session, user["id"]) == "ghu_2"
    assert github.access_token(db_session, user["id"]) == "ghu_2"
    assert fake_github.valid_refresh == {"ghr_2"}


def test_a_refused_refresh_drops_the_connection(client, fake_github, db_session):
    user = create_user(client, USER_EMAIL)
    _connect(client, USER_EMAIL, user["id"])
    _expire(db_session)
    fake_github.refuse_refresh = True
    with pytest.raises(github.GitNotConnectedException):
        github.access_token(db_session, user["id"])
    assert db_session.exec(select(GitConnectionORM)).first() is None


def test_an_expired_refresh_token_drops_the_connection_without_asking(client, fake_github, db_session):
    user = create_user(client, USER_EMAIL)
    _connect(client, USER_EMAIL, user["id"])
    _expire(db_session, refresh_too=True)
    calls = len(fake_github.calls)
    with pytest.raises(github.GitNotConnectedException):
        github.access_token(db_session, user["id"])
    assert len(fake_github.calls) == calls
    assert db_session.exec(select(GitConnectionORM)).first() is None


# ── Installations and disconnecting ───────────────────────────────────


def test_installations_are_listed(client, fake_github):
    user = create_user(client, USER_EMAIL)
    _connect(client, USER_EMAIL, user["id"])
    response = client.get(
        f"/api/users/{user['id']}/git/github/installations", headers=auth_header(USER_EMAIL)
    )
    assert response.status_code == 200
    assert response.json() == [
        {
            "id": 77,
            "account": "alice",
            "account_type": "User",
            "repository_selection": "selected",
            "html_url": "https://github.com/settings/installations/77",
        }
    ]


def test_installations_need_a_connection(client, fake_github):
    user = create_user(client, USER_EMAIL)
    response = client.get(
        f"/api/users/{user['id']}/git/github/installations", headers=auth_header(USER_EMAIL)
    )
    assert response.status_code == 409
    assert response.json()["code"] == "git_not_connected"


def test_disconnecting_revokes_the_grant(client, fake_github, db_session):
    user = create_user(client, USER_EMAIL)
    _connect(client, USER_EMAIL, user["id"])
    response = client.delete(
        f"/api/users/{user['id']}/git/github", headers=auth_header(USER_EMAIL)
    )
    assert response.status_code == 204
    assert fake_github.revoked == ["ghu_1"]
    assert db_session.exec(select(GitConnectionORM)).first() is None
    again = client.delete(f"/api/users/{user['id']}/git/github", headers=auth_header(USER_EMAIL))
    assert again.status_code == 409


def test_other_accounts_cannot_read_connections(client, fake_github):
    user = create_user(client, USER_EMAIL)
    create_user(client, OTHER_EMAIL)
    response = client.get(f"/api/users/{user['id']}/git", headers=auth_header(OTHER_EMAIL))
    assert response.status_code == 403


# ── Operator CLI ──────────────────────────────────────────────────────


def test_cli_lists_and_disconnects(cli_runner, fake_github, db_session):
    from app.models import UserORM

    runner, cli = cli_runner
    user = db_session.exec(select(UserORM).where(UserORM.email == "cli-test@example.com")).one()
    state = github.sign_state(github.config(), user.id)
    github.complete_authorization(db_session, user.id, code="code-alice", state=state)

    listed = runner.invoke(cli, ["git", "list"])
    assert listed.exit_code == 0, listed.output
    assert "login: alice" in listed.output

    connect = runner.invoke(cli, ["git", "connect"])
    assert connect.exit_code == 0 and "authorize_url: https://github.com/login/oauth/authorize" in connect.output

    gone = runner.invoke(cli, ["git", "disconnect"])
    assert gone.exit_code == 0, gone.output
    assert fake_github.revoked == ["ghu_1"]
    assert runner.invoke(cli, ["git", "disconnect"]).exit_code == 1
