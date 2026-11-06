"""The API's host guard and the parking page (parking-page)."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.config import CaelusSettings
from app.deps import get_current_user, get_session
from app.main import app

DOMAIN = "freepod.eu"
TENANT = "photos-alice.freepod.app"
PEER = ("10.42.0.7", 41000)  # Traefik's pod address


@pytest.fixture
def domain(monkeypatch):
    def set_domain(value: str = DOMAIN) -> None:
        monkeypatch.setattr("app.parking.get_settings", lambda: CaelusSettings(domain=value, _env_file=None))

    set_domain()
    return set_domain


@pytest.fixture
def reached():
    """Records whether any route dependency ran."""
    calls: list[str] = []

    def spy():
        calls.append("dependency")
        raise AssertionError("a route dependency ran")

    app.dependency_overrides[get_current_user] = spy
    app.dependency_overrides[get_session] = spy
    yield calls
    app.dependency_overrides.clear()


def _client(peer=PEER, asgi=app) -> TestClient:
    return TestClient(asgi, base_url=f"http://{TENANT}", client=peer, raise_server_exceptions=False)


def test_forged_identity_headers_get_the_parking_response(domain, reached):
    resp = _client().get(
        "/api/users/me",
        headers={"X-Auth-Request-Email": "admin@example.com", "X-Auth-Request-User": "someone"},
    )
    assert resp.status_code == 503
    assert resp.text == f"{TENANT} is stopped.\n"
    assert reached == []


@pytest.mark.parametrize("method", ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def test_every_method_is_parked(domain, reached, method):
    resp = _client().request(method, "/anything", content=b"secret" if method in ("POST", "PUT", "PATCH") else None)
    assert resp.status_code == 503
    assert resp.headers["cache-control"] == "no-store"
    assert reached == []


def test_a_browser_gets_the_branded_page(domain):
    resp = _client().get("/", headers={"Accept": "text/html,application/xhtml+xml"})
    assert resp.status_code == 503
    assert resp.headers["content-type"] == "text/html; charset=utf-8"
    assert resp.headers["cache-control"] == "no-store"
    assert f"<h1>{TENANT} is stopped.</h1>" in resp.text
    assert "Freepod" in resp.text


@pytest.mark.parametrize(
    "headers",
    [{"Accept": "application/json"}, {"Accept": "text/html", "Upgrade": "h2c"}, {}],
    ids=["json", "upgrade", "no-accept"],
)
def test_anything_else_gets_plain_text(domain, headers):
    resp = _client().get("/", headers=headers)
    assert resp.status_code == 503
    assert resp.headers["content-type"] == "text/plain; charset=utf-8"
    assert resp.text == f"{TENANT} is stopped.\n"


def test_a_post_accepting_html_gets_plain_text(domain):
    resp = _client().post("/", headers={"Accept": "text/html"})
    assert resp.headers["content-type"] == "text/plain; charset=utf-8"


def test_markup_in_the_host_is_escaped(domain):
    resp = _client().get("/", headers={"Host": '<script>x</script>"', "Accept": "text/html"})
    assert resp.status_code == 503
    assert "<script>" not in resp.text
    assert "&lt;script&gt;x&lt;/script&gt;&quot;" in resp.text


def test_the_port_is_stripped_from_the_host(domain):
    resp = _client().get("/", headers={"Host": f"{TENANT}:443"})
    assert resp.text == f"{TENANT} is stopped.\n"


@pytest.mark.parametrize("host", [DOMAIN, "FreePod.EU", f"{DOMAIN}:443"])
def test_the_platform_domain_passes(client, domain, host):
    resp = TestClient(app, client=PEER).get("/api/openapi.json", headers={"Host": host})
    assert resp.status_code == 200
    assert resp.json()["info"]["title"] == "Freepod"


@pytest.mark.parametrize("peer", [("127.0.0.1", 50000), ("::1", 50000)])
def test_a_loopback_peer_passes(domain, peer):
    resp = _client(peer=peer).get("/api/openapi.json")
    assert resp.status_code == 200


def test_a_forwarded_loopback_address_from_another_peer_is_parked(domain, reached):
    # The proxy-headers handling uvicorn runs in front of the app, with its
    # default trust: only a loopback peer may rewrite the client address.
    asgi = ProxyHeadersMiddleware(app, trusted_hosts="127.0.0.1")
    resp = _client(asgi=asgi).get(
        "/api/users/me",
        headers={"X-Forwarded-For": "127.0.0.1", "X-Auth-Request-Email": "admin@example.com"},
    )
    assert resp.status_code == 503
    assert reached == []


def test_a_websocket_to_a_foreign_host_is_refused(domain):
    with pytest.raises(WebSocketDisconnect):
        with _client().websocket_connect("/api/anything"):
            pass


def test_no_domain_passes_everything(domain):
    domain("")
    resp = TestClient(app, base_url="http://localhost:5173", client=PEER).get("/api/openapi.json")
    assert resp.status_code == 200


@pytest.mark.parametrize("path", ["/healthz", "/api/openapi.json", "/api/docs"])
def test_no_tenant_path_is_reserved(domain, path):
    resp = _client().get(path)
    assert resp.status_code == 503
    assert resp.text == f"{TENANT} is stopped.\n"
