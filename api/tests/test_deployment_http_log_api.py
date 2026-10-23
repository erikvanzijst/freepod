"""The HTTP access log endpoint: the record on the wire, isolation and failure modes.

Shares the pod-log endpoint's fake store and fixtures; the transport, resume and
keepalive behavior underneath is the same code and is tested there.
"""

from __future__ import annotations

import json

import pytest

from app.models import DeploymentORM
from app.services import http_logs, log_stream
from app.services.deployment_logs import LogTarget
from app.services.loki import LogEntry, LokiException
from tests.conftest import client, db_session  # noqa: F401
from tests.conftest import create_user
from tests.test_deployment_log_api import (  # noqa: F401
    TS1,
    TS2,
    _events,
    _log_settings,
    _setup,
    loki,
)


def _request(ts, path="/", status=200, **extra):
    line = {
        "ClientHost": "203.0.113.7",
        "DownstreamContentSize": 512,
        "DownstreamStatus": status,
        "Duration": 1_500_000,
        "RequestHost": "app.example.test",
        "RequestMethod": "GET",
        "RequestPath": path,
        "RequestProtocol": "HTTP/2.0",
        "RouterName": "ns-app-ingress-app-example-test@kubernetes",
        "StartUTC": "2026-10-23T12:50:48.123456789Z",
        "request_User-Agent": "Mozilla/5.0",
        **extra,
    }
    return LogEntry(timestamp_ns=ts, line=json.dumps(line), labels={"router": "x"})


def _url(user_id, deployment_id):
    return f"/api/users/{user_id}/deployments/{deployment_id}/http-log"


def test_a_bounded_read_emits_one_request_event_per_request(client, db_session, loki):
    user_id, _, deployment_id = _setup(client, db_session, "http-read@example.com")
    loki([[_request(TS1, "/a"), _request(TS2, "/b", status=404)]])

    resp = client.get(_url(user_id, deployment_id))

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _events(resp.text)
    assert [e["event"] for e in events] == ["request", "request", "end"]
    first = events[0]["data"]
    assert first["ts"] == TS1 and isinstance(first["ts"], str)
    assert events[0]["id"] == TS1
    assert (first["path"], first["status"], first["duration_ms"]) == ("/a", 200, 1.5)
    assert first["referer"] is None
    assert "RouterName" not in first and "router" not in first
    assert events[1]["data"]["status"] == 404


def test_lines_that_are_not_request_records_are_skipped(client, db_session, loki):
    user_id, _, deployment_id = _setup(client, db_session, "http-skip@example.com")
    clf = LogEntry(
        timestamp_ns=TS1,
        line='1.2.3.4 - - [23/Oct/2026:12:52:20 +0000] "GET /old HTTP/2.0" 404 0 "-" "-"',
        labels={},
    )
    loki([[clf, _request(TS2, "/new")]])

    events = _events(client.get(_url(user_id, deployment_id)).text)

    assert [e["data"].get("path") for e in events if e["event"] == "request"] == ["/new"]


def test_no_requests_is_an_empty_stream_not_an_error(client, db_session, loki):
    user_id, _, deployment_id = _setup(client, db_session, "http-empty@example.com")
    loki([[]])

    resp = client.get(_url(user_id, deployment_id))

    assert resp.status_code == 200
    assert _events(resp.text) == [{"event": "end", "data": {"reason": "complete"}}]


def test_the_selector_is_the_deployments_router_prefix(client, db_session, loki):
    user_id, _, deployment_id = _setup(client, db_session, "http-selector@example.com")
    fake = loki([[]])

    client.get(_url(user_id, deployment_id))

    deployment = db_session.get(DeploymentORM, deployment_id)
    target = LogTarget(
        deployment_id=str(deployment.id), namespace=deployment.namespace, name=deployment.name
    )
    assert fake.queries[0]["query"] == http_logs.build_selector(target)
    assert fake.queries[0]["direction"] == "backward"


@pytest.mark.parametrize(
    "param", ["query", "selector", "router", "namespace", "logql", "expr", "instance"]
)
def test_a_client_supplied_selector_has_no_effect_on_the_query(client, db_session, loki, param):
    user_id, _, deployment_id = _setup(client, db_session, f"http-inj{param}@example.com")
    fake = loki([[]])

    client.get(_url(user_id, deployment_id), params={param: '{namespace="caelus-api"}'})

    deployment = db_session.get(DeploymentORM, deployment_id)
    target = LogTarget(
        deployment_id=str(deployment.id), namespace=deployment.namespace, name=deployment.name
    )
    assert fake.queries[0]["query"] == http_logs.build_selector(target)
    assert "caelus-api" not in fake.queries[0]["query"]


def test_a_release_parameter_has_no_effect(client, db_session, loki):
    user_id, _, deployment_id = _setup(client, db_session, "http-release@example.com")
    fake = loki([[]])

    resp = client.get(_url(user_id, deployment_id), params={"release": 1})

    assert resp.status_code == 200
    assert "release_id" not in fake.queries[0]["query"]


def test_a_window_and_a_resume_point_behave_as_on_the_pod_log(
    client, db_session, loki, _log_settings
):
    user_id, _, deployment_id = _setup(client, db_session, "http-window@example.com")
    fake = loki([[], []])

    client.get(_url(user_id, deployment_id), params={"since": TS1, "lookback": 60})
    too_long = client.get(
        _url(user_id, deployment_id),
        params={"lookback": _log_settings.log_initial_lookback_seconds + 1},
    )

    assert fake.queries[0]["start_ns"] == int(TS1)
    assert fake.queries[0]["direction"] == "forward"
    assert too_long.status_code == 400
    assert len(fake.queries) == 1


def test_another_users_deployment_is_404(client, db_session, loki):
    _, _, deployment_id = _setup(client, db_session, "http-owner@example.com")
    intruder_id = create_user(client, "http-intruder@example.com")["id"]
    fake = loki([[]])

    resp = client.get(_url(intruder_id, deployment_id))

    assert resp.status_code == 404
    assert fake.queries == []


def test_an_unreachable_store_is_503_not_an_empty_success(client, db_session, loki):
    user_id, _, deployment_id = _setup(client, db_session, "http-down@example.com")
    loki(raises=LokiException("connection refused"))

    resp = client.get(_url(user_id, deployment_id))

    assert resp.status_code == 503
    assert "Log store is unavailable" in resp.json()["detail"]


def test_http_and_pod_log_streams_share_one_limit(client, db_session, loki, _log_settings):
    user_id, _, deployment_id = _setup(client, db_session, "http-limit@example.com")
    loki([[], []])
    caller_id = client.get("/api/me").json()["id"]
    limit = _log_settings.log_max_streams_per_user

    # Streams held open as the pod-log endpoint holds them.
    for _ in range(limit):
        log_stream.stream_registry.acquire(caller_id, limit=limit)
    try:
        resp = client.get(_url(user_id, deployment_id))
        assert resp.status_code == 400
        assert "concurrent log streams" in resp.json()["detail"]
    finally:
        for _ in range(limit):
            log_stream.stream_registry.release(caller_id)

    assert client.get(_url(user_id, deployment_id)).status_code == 200
    assert log_stream.stream_registry.open_count(caller_id) == 0
