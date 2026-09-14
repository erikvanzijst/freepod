from __future__ import annotations

import base64
import json
import shutil
import subprocess
import time
from datetime import UTC, datetime

import httpx
import jwt
import pytest
import yaml

from app.config import CaelusSettings
from app.models import UserORM
from app.services import registry_tokens
from tests.conftest import create_user

HOST = "cr.test.example"
ISSUER = "caelus-test"
HMAC_KEY = "test-pull-hmac-key"
URL = "/api/registry/token"
TTL = registry_tokens.PULL_TOKEN_TTL_SECONDS

# The image tf/app/registry deploys.
REGISTRY_IMAGE = "docker.io/library/registry:3.1.1"


def _settings(key) -> CaelusSettings:
    return CaelusSettings(
        _env_file=None,
        registry_host=HOST,
        registry_token_issuer=ISSUER,
        registry_signing_private_key=registry_tokens.private_key_pem(key),
        registry_pull_hmac_key=HMAC_KEY,
    )


@pytest.fixture(scope="module")
def signing_key():
    return registry_tokens.generate_private_key()


@pytest.fixture(autouse=True)
def _registry_settings(monkeypatch, signing_key):
    monkeypatch.setattr("app.api.registry.get_settings", lambda: _settings(signing_key))


@pytest.fixture
def owner(client) -> int:
    return create_user(client, "owner@example.com")["id"]


def _password(uid: int, version: str = registry_tokens.PULL_CREDENTIAL_VERSION) -> str:
    return registry_tokens.pull_password(HMAC_KEY, uid, version=version)


def _form(client, uid, *, scope, username=None, password=None, service=HOST):
    return client.post(
        URL,
        data={
            "grant_type": "password",
            "service": service,
            "client_id": "containerd-client",
            "username": username or f"pull-{uid}",
            "password": _password(uid) if password is None else password,
            "scope": scope,
        },
    )


def _header(client, uid, *, scope, username=None, password=None, service=HOST):
    pair = f"{username or f'pull-{uid}'}:{_password(uid) if password is None else password}"
    scopes = scope.split()
    return client.get(
        URL,
        params=[("service", service), *(("scope", s) for s in scopes)],
        headers={"Authorization": "Basic " + base64.b64encode(pair.encode()).decode()},
    )


def _token(resp) -> str:
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return body["access_token"]


def _access(resp, key) -> list[dict]:
    claims = jwt.decode(_token(resp), key.public_key(), algorithms=["ES256"], audience=HOST, issuer=ISSUER)
    return claims["access"]


def _own_pull(uid: int) -> list[dict]:
    return [{"type": "repository", "name": f"u/{uid}", "actions": ["pull"]}]


# ── 3.1: both exchanges succeed on the first request ─────────────────────────


def test_the_form_exchange_issues_a_token(client, owner, signing_key):
    resp = _form(client, owner, scope=f"repository:u/{owner}:pull")
    assert _access(resp, signing_key) == _own_pull(owner)
    body = resp.json()
    assert body["expires_in"] == TTL
    assert body["scope"] == f"repository:u/{owner}:pull"
    assert datetime.fromisoformat(body["issued_at"]).tzinfo == UTC


def test_the_header_exchange_issues_a_token(client, owner, signing_key):
    resp = _header(client, owner, scope=f"repository:u/{owner}:pull")
    assert _access(resp, signing_key) == _own_pull(owner)
    body = resp.json()
    assert body["token"] == body["access_token"]
    assert body["expires_in"] == TTL


def test_no_session_identity_is_needed(client, owner, signing_key):
    client.headers.pop("X-Auth-Request-Email", None)
    assert _access(_form(client, owner, scope=f"repository:u/{owner}:pull"), signing_key)


@pytest.mark.parametrize("exchange", [_form, _header])
def test_the_token_carries_what_the_registry_verifies(client, owner, signing_key, exchange):
    token = _token(exchange(client, owner, scope=f"repository:u/{owner}:pull"))
    header = jwt.get_unverified_header(token)
    assert header["alg"] == "ES256"
    assert header["kid"] == registry_tokens.key_id(signing_key.public_key())
    claims = jwt.decode(token, signing_key.public_key(), algorithms=["ES256"], audience=HOST, issuer=ISSUER)
    assert claims["sub"] == f"pull-{owner}"
    assert claims["exp"] - claims["iat"] == TTL
    assert claims["nbf"] <= claims["iat"]


# ── 3.2: a credential that proves nothing yields no token ────────────────────


@pytest.mark.parametrize("exchange", [_form, _header])
def test_a_wrong_password_yields_no_token(client, owner, exchange):
    resp = exchange(client, owner, scope=f"repository:u/{owner}:pull", password="nope")
    assert resp.status_code == 401


@pytest.mark.parametrize("exchange", [_form, _header])
def test_an_unknown_user_yields_no_token(client, owner, exchange):
    stranger = owner + 1000
    assert exchange(client, stranger, scope=f"repository:u/{stranger}:pull").status_code == 401


def test_a_deleted_user_yields_no_token(client, owner, db_session):
    user = db_session.get(UserORM, owner)
    user.deleted_at = datetime.now(UTC)
    db_session.add(user)
    db_session.commit()
    assert _form(client, owner, scope=f"repository:u/{owner}:pull").status_code == 401


@pytest.mark.parametrize("username", ["admin", "pull-", "pull-0", "pull-5x", "PULL-5"])
def test_a_malformed_username_yields_no_token(client, owner, username):
    assert _form(client, owner, scope="", username=username).status_code == 401


@pytest.mark.parametrize("exchange", [_form, _header])
def test_a_mismatched_version_marker_yields_no_token(client, owner, exchange):
    resp = exchange(client, owner, scope=f"repository:u/{owner}:pull", password=_password(owner, "v2"))
    assert resp.status_code == 401


def test_a_request_without_a_credential_yields_no_token(client, owner):
    resp = client.get(URL, params={"service": HOST, "scope": f"repository:u/{owner}:pull"})
    assert resp.status_code == 401


# ── 3.3: the grant is the intersection, and never more than pull ─────────────


def test_push_is_trimmed_to_pull(client, owner, signing_key):
    resp = _form(client, owner, scope=f"repository:u/{owner}:pull,push")
    assert _access(resp, signing_key) == _own_pull(owner)


@pytest.mark.parametrize(
    "scope",
    [
        "repository:u/{owner}:push",
        "repository:u/{owner}:delete",
        "repository:u/{other}:pull",
        "repository:u/{owner}0:pull",
        "repository:u/{owner}/x:pull",
        "repository:cache/{owner}:pull",
        "registry:catalog:*",
        "",
    ],
)
@pytest.mark.parametrize("exchange", [_form, _header])
def test_nothing_beyond_the_owners_pull_is_granted(client, owner, signing_key, scope, exchange):
    scope = scope.format(owner=owner, other=owner + 1)
    assert _access(exchange(client, owner, scope=scope), signing_key) == []


@pytest.mark.parametrize("exchange", [_form, _header])
def test_a_mixed_request_keeps_only_the_permitted_part(client, owner, signing_key, exchange):
    scope = (
        f"repository:u/{owner}:pull,push,delete "
        f"repository:u/{owner + 1}:pull "
        "registry:catalog:*"
    )
    assert _access(exchange(client, owner, scope=scope), signing_key) == _own_pull(owner)


# ── Refusals that are not about the credential ──────────────────────────────


def test_another_service_is_refused(client, owner):
    resp = _form(client, owner, scope="", service="cr.elsewhere.example")
    assert resp.status_code == 400
    assert resp.json()["code"] == "unknown_service"


def test_an_unsupported_grant_is_refused(client, owner):
    resp = client.post(URL, data={"grant_type": "refresh_token", "service": HOST, "refresh_token": "x"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "unsupported_grant_type"


def test_an_unconfigured_endpoint_is_unavailable(client, owner, monkeypatch, signing_key):
    unconfigured = _settings(signing_key).model_copy(update={"registry_signing_private_key": ""})
    monkeypatch.setattr("app.api.registry.get_settings", lambda: unconfigured)
    assert _form(client, owner, scope="").status_code == 503


# ── 3.4: the real registry accepts what the endpoint mints ───────────────────


def _docker_usable() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


needs_docker = pytest.mark.skipif(not _docker_usable(), reason="docker not usable")


def _default_gateway() -> str | None:
    """The host's address as seen from inside a container, where tests run."""
    try:
        with open("/proc/net/route") as routes:
            for line in routes.readlines()[1:]:
                fields = line.split()
                if fields[1] == "00000000":
                    return ".".join(str(b) for b in bytes.fromhex(fields[2])[::-1])
    except OSError:
        pass
    return None


def _reachable(port: str) -> str:
    candidates = [h for h in (_default_gateway(), "127.0.0.1") if h]
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        for host in candidates:
            url = f"http://{host}:{port}"
            try:
                if httpx.get(f"{url}/v2/", timeout=2).status_code == 401:
                    return url
            except httpx.HTTPError:
                pass
        time.sleep(0.5)
    raise RuntimeError(f"registry on port {port} never answered on {candidates}")


@pytest.fixture(scope="module")
def registry_url(signing_key):
    config = yaml.safe_dump(
        {
            "version": "0.1",
            "log": {"level": "warn"},
            "storage": {"filesystem": {"rootdirectory": "/var/lib/registry"}},
            "http": {"addr": ":5000"},
            "auth": {
                "token": {
                    "realm": "https://api.test.example/api/registry/token",
                    "service": HOST,
                    "issuer": ISSUER,
                    "jwks": "/tmp/jwks.json",
                    "signingalgorithms": ["ES256"],
                }
            },
        }
    )
    trusted = json.dumps(registry_tokens.jwks(signing_key.public_key()))
    # Files travel as environment variables: the daemon may not share this
    # container's filesystem, so a bind mount cannot carry them.
    container = subprocess.run(
        [
            "docker", "run", "-d", "--rm", "-p", "5000",
            "-e", f"CONFIG={config}", "-e", f"JWKS={trusted}",
            "--entrypoint", "sh", REGISTRY_IMAGE, "-c",
            'printf "%s" "$CONFIG" > /tmp/config.yml && printf "%s" "$JWKS" > /tmp/jwks.json'
            " && exec registry serve /tmp/config.yml",
        ],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    try:
        published = subprocess.run(
            ["docker", "port", container, "5000/tcp"], check=True, capture_output=True, text=True
        ).stdout.splitlines()[0]
        yield _reachable(published.rsplit(":", 1)[1])
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True)


@needs_docker
def test_the_registry_accepts_what_the_endpoint_mints(client, owner, registry_url):
    other = create_user(client, "other-owner@example.com")["id"]
    token = _token(_form(client, owner, scope=f"repository:u/{owner}:pull repository:u/{other}:pull"))
    auth = {"Authorization": f"Bearer {token}"}

    assert httpx.get(f"{registry_url}/v2/", headers=auth).status_code == 200
    own = httpx.get(f"{registry_url}/v2/u/{owner}/tags/list", headers=auth)
    assert own.status_code == 404, own.text
    assert own.json()["errors"][0]["code"] == "NAME_UNKNOWN"
    assert httpx.get(f"{registry_url}/v2/u/{other}/tags/list", headers=auth).status_code == 401
    assert httpx.get(f"{registry_url}/v2/_catalog", headers=auth).status_code == 401


@needs_docker
def test_the_registry_refuses_a_token_signed_by_another_key(client, owner, registry_url, monkeypatch):
    stranger = registry_tokens.generate_private_key()
    monkeypatch.setattr("app.api.registry.get_settings", lambda: _settings(stranger))
    token = _token(_form(client, owner, scope=f"repository:u/{owner}:pull"))
    resp = httpx.get(f"{registry_url}/v2/", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
