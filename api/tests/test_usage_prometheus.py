"""The Prometheus instant-query transport, and the OpenCost trust check built on it."""

from __future__ import annotations

from datetime import datetime

import httpx
import pytest

from app.services.usage.opencost import OpenCostClient, OpenCostException
from app.services.usage.prometheus import PrometheusClient, PrometheusException

AT = datetime(2026, 10, 6, 14)


def _client(handler) -> PrometheusClient:
    return PrometheusClient(
        "http://prometheus/", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_a_result_is_returned_and_the_query_sent_at_the_given_time():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(path=request.url.path, **request.url.params)
        return httpx.Response(
            200, json={"data": {"result": [{"metric": {"a": "b"}, "value": [0, "1"]}]}}
        )

    result = _client(handler).query("up", AT)
    assert result == [{"metric": {"a": "b"}, "value": [0, "1"]}]
    assert seen == {"path": "/api/v1/query", "query": "up", "time": "2026-10-06T14:00:00Z"}


def test_an_empty_result_is_an_answer():
    assert _client(lambda r: httpx.Response(200, json={"data": {"result": []}})).query("up", AT) == []


def test_a_non_200_raises():
    with pytest.raises(PrometheusException, match="503"):
        _client(lambda r: httpx.Response(503)).query("up", AT)


def test_an_unreachable_host_raises():
    def handler(request):
        raise httpx.ConnectError("down")

    with pytest.raises(PrometheusException, match="request failed"):
        _client(handler).query("up", AT)


def test_an_unconfigured_client_raises():
    with pytest.raises(PrometheusException, match="not configured"):
        PrometheusClient("").query("up", AT)


def test_the_opencost_trust_check_still_raises_its_own_exception():
    """`read_window` catches OpenCostException; a Prometheus failure must stay one."""
    client = OpenCostClient(
        "http://opencost:9003",
        prometheus_url="http://prometheus",
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))),
    )
    with pytest.raises(OpenCostException, match="500"):
        client.allocation_series_cover(datetime(2026, 10, 6, 13), AT)
