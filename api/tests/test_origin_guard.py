"""platform-apex-edge: state-changing requests from other origins' pages."""
from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.origin_guard import OriginGuard


def _client() -> TestClient:
    async def ok(_):
        return PlainTextResponse("ok")

    inner = Starlette(routes=[Route("/x", ok, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])])
    return TestClient(OriginGuard(inner, trusted_origins=["http://localhost:5173"]), base_url="https://freepod.test")


@pytest.mark.parametrize(
    ("method", "headers", "status"),
    [
        ("POST", {}, 200),
        ("POST", {"Sec-Fetch-Site": "same-origin"}, 200),
        ("POST", {"Sec-Fetch-Site": "none"}, 200),
        ("POST", {"Sec-Fetch-Site": "same-site"}, 403),
        ("DELETE", {"Sec-Fetch-Site": "cross-site"}, 403),
        ("PUT", {"Origin": "https://app.freepod.test"}, 403),
        ("PATCH", {"Origin": "https://freepod.test"}, 200),
        ("POST", {"Origin": "http://localhost:5173", "Sec-Fetch-Site": "same-site"}, 200),
        ("GET", {"Sec-Fetch-Site": "cross-site"}, 200),
    ],
)
def test_state_changing_requests_from_other_origins_are_refused(method, headers, status):
    assert _client().request(method, "/x", headers=headers).status_code == status


def test_the_api_refuses_them_before_routing():
    from app.main import app

    resp = TestClient(app).post("/api/artifacts", headers={"Sec-Fetch-Site": "same-site"})
    assert resp.status_code == 403
    assert resp.json() == {"detail": "Cross-origin request refused"}
