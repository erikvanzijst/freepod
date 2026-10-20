"""Requests from `freepod` CLIs older than the minimum are refused with 426."""

import pytest
from packaging.version import Version

from app.client_version_gate import MIN_CLIENT_VERSION, ClientVersionGate


def _older(version: Version) -> str:
    return f"{version.major}.{version.minor - 1}.9" if version.minor else f"{version.major - 1}.99.0"


@pytest.mark.parametrize("path", ["/api/me", "/api/cname-target", "/api/no-such-route"])
def test_an_old_client_is_refused_everywhere(client, path):
    """Including a route that skips authentication, and one that does not exist."""
    resp = client.get(path, headers={"User-Agent": f"freepod/{_older(MIN_CLIENT_VERSION)}"})

    assert resp.status_code == 426
    assert resp.json()["code"] == "client_upgrade_required"


def test_the_refusal_says_how_to_upgrade(client):
    resp = client.get("/api/me", headers={"User-Agent": "freepod/0.1.1 (+https://freepod.eu)"})

    detail = resp.json()["detail"]
    assert str(MIN_CLIENT_VERSION) in detail
    assert "uv tool upgrade freepod" in detail


def test_an_old_client_does_not_run_the_endpoint(client, monkeypatch):
    called = []
    monkeypatch.setattr("app.api.hostnames.get_settings", lambda: called.append(1))

    client.get("/api/cname-target", headers={"User-Agent": "freepod/0.1.1"})

    assert called == []


@pytest.mark.parametrize(
    "agent",
    [
        f"freepod/{MIN_CLIENT_VERSION}",
        f"freepod/{MIN_CLIENT_VERSION.major}.{MIN_CLIENT_VERSION.minor + 1}.1 (+https://freepod.eu)",
    ],
)
def test_a_current_client_passes(client, agent):
    assert client.get("/api/cname-target", headers={"User-Agent": agent}).status_code == 200


def test_versions_compare_numerically():
    gate = ClientVersionGate(app=None, minimum=Version("0.9.0"))
    scope = {"headers": [(b"user-agent", b"freepod/0.10.0")]}

    assert gate._outdated(scope) is False


@pytest.mark.parametrize(
    "agent",
    ["Mozilla/5.0 (X11; Linux x86_64) Firefox/140.0", "freepod/unknown", "python-httpx/0.28", ""],
)
def test_other_agents_pass(client, agent):
    assert client.get("/api/cname-target", headers={"User-Agent": agent}).status_code == 200
