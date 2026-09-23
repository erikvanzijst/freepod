"""The OpenCost client, against responses recorded from the live cluster.

Both fixtures are real `/allocation` output captured on 2026-09-23:
`opencost_allocation.json` from windows after OpenCost's own exporter was being
scraped, `opencost_allocation_degraded.json` from before it was — the regime where no
controller resolves. They are separate files because the two never coexist in one
response.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app.services.usage.opencost import (
    AGGREGATE_BY,
    Allocation,
    OpenCostClient,
    OpenCostException,
    parse_allocations,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    """`parse_float=Decimal`, exactly as the client parses a live response."""
    return json.loads((FIXTURES / name).read_text(), parse_float=Decimal)


@pytest.fixture
def healthy() -> dict:
    return _load("opencost_allocation.json")


@pytest.fixture
def degraded() -> dict:
    return _load("opencost_allocation_degraded.json")


@pytest.fixture
def healthy_body() -> str:
    """The fixture as bytes on the wire, so the client does its own parsing."""
    return (FIXTURES / "opencost_allocation.json").read_text()


def _by_container(allocations: list[Allocation]) -> dict[str, Allocation]:
    return {a.container: a for a in allocations}


def test_each_window_is_parsed_separately(healthy):
    windows = parse_allocations(healthy)
    assert len(windows) == 2
    assert all(windows)


def test_identity_comes_from_properties_without_the_key_prefix(healthy):
    """The response key reads `deployment:bookstack-...`; properties does not."""
    app = _by_container(parse_allocations(healthy)[0])["bookstack"]
    assert app.namespace == "bookstack-fred-mi4dpvrph"
    assert app.controller_kind == "deployment"
    assert app.controller == "bookstack-8d56q1-bookstack"
    assert not app.controller.startswith("deployment:")
    assert app.is_resolved


def test_quantities_and_minutes_are_parsed(healthy):
    app = _by_container(parse_allocations(healthy)[0])["bookstack"]
    assert app.minutes == 60
    for field in (
        "cpuCoreHours",
        "cpuCoreUsageAverage",
        "cpuCoreRequestAverage",
        "cpuCoreLimitAverage",
        "ramByteHours",
        "ramByteUsageAverage",
        "ramByteRequestAverage",
        "ramByteLimitAverage",
        "networkTransferBytes",
        "networkReceiveBytes",
        "pvByteHours",
    ):
        assert field in app.fields, field
    assert app.fields["cpuCoreHours"] > 0
    assert str(app.minutes) == "60"


def test_the_window_is_parsed_as_naive_utc(healthy):
    app = _by_container(parse_allocations(healthy)[0])["bookstack"]
    assert app.window_start.tzinfo is None
    assert app.window_end - app.window_start == (
        datetime(2026, 1, 1, 1) - datetime(2026, 1, 1, 0)
    )


def test_a_non_zulu_offset_is_converted_not_stripped():
    """Stripping would store the window at the wrong instant, and off the grid."""
    from app.services.usage.opencost import _parse_window

    utc = _parse_window("2026-09-23T10:00:00Z")
    assert _parse_window("2026-09-23T12:00:00+02:00") == utc
    assert _parse_window("2026-09-23T06:00:00-04:00") == utc


def test_a_containers_sidecar_is_its_own_allocation(healthy):
    """Container granularity is what lets the SSH sidecar be separated later."""
    first = _by_container(parse_allocations(healthy)[0])
    assert {"bookstack", "ssh", "mysql"} <= first.keys()
    assert first["ssh"].namespace == first["bookstack"].namespace
    assert first["ssh"].controller == first["bookstack"].controller


def test_unmounted_buckets_are_flagged_and_carry_a_namespace(healthy):
    """The reason they are recognized by container name, not by a missing namespace."""
    unmounted = [a for a in parse_allocations(healthy)[0] if a.is_unmounted]
    assert unmounted
    with_namespace = [a for a in unmounted if a.namespace]
    assert with_namespace, "a PV bucket carrying a tenant namespace is the case to skip"


def test_an_unresolved_controller_is_none_not_a_vendor_token(degraded):
    """`__unallocated__` is translated at the boundary so it never reaches the ledger."""
    allocations = parse_allocations(degraded)[0]
    workloads = [a for a in allocations if not a.is_unmounted]
    assert workloads
    for allocation in workloads:
        assert allocation.controller is None
        assert allocation.controller_kind is None
        assert not allocation.is_resolved
        assert allocation.namespace


def _client(handler, **kwargs) -> OpenCostClient:
    return OpenCostClient(
        "http://opencost:9003",
        prometheus_url="http://prometheus",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        **kwargs,
    )


def test_fetch_requests_the_four_field_aggregation(healthy_body):
    """`aggregate=container` would drop the namespace and make attribution impossible."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        return httpx.Response(
            200, content=healthy_body, headers={"content-type": "application/json"}
        )

    windows = _client(handler).fetch_allocations(
        datetime(2026, 9, 23, 8), datetime(2026, 9, 23, 10)
    )

    assert seen["aggregate"] == AGGREGATE_BY
    assert seen["step"] == "1h"
    assert seen["window"] == "2026-09-23T08:00:00Z,2026-09-23T10:00:00Z"
    assert len(windows) == 2
    assert all(isinstance(v, Decimal) for a in windows[0] for v in a.fields.values())


def test_a_non_200_raises_rather_than_reading_as_empty():
    """Unreachable and 'reported nothing' are different answers."""
    client = _client(lambda request: httpx.Response(503))
    with pytest.raises(OpenCostException, match="503"):
        client.fetch_allocations(datetime(2026, 9, 23, 8), datetime(2026, 9, 23, 9))


def test_the_presence_check_reads_a_covered_window_as_trustworthy():
    """Recorded from Prometheus: a healthy hour answers with a series count."""
    covered = {"data": {"result": [{"metric": {}, "value": [1790161200, "126"]}]}}
    client = _client(lambda request: httpx.Response(200, json=covered))
    assert client.allocation_series_cover(
        datetime(2026, 9, 23, 10), datetime(2026, 9, 23, 11)
    )


def test_the_presence_check_reads_an_uncovered_window_as_untrustworthy():
    """The pre-scrape hour answers 200 with an empty result -- not an error."""
    empty = {"data": {"result": []}}
    client = _client(lambda request: httpx.Response(200, json=empty))
    assert not client.allocation_series_cover(
        datetime(2026, 9, 23, 7), datetime(2026, 9, 23, 8)
    )


def test_the_presence_check_spans_exactly_the_window():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        return httpx.Response(200, json={"data": {"result": []}})

    _client(handler).allocation_series_cover(
        datetime(2026, 9, 23, 7), datetime(2026, 9, 23, 8)
    )
    assert "container_cpu_allocation[3600s]" in seen["query"]
    assert seen["time"] == "2026-09-23T08:00:00Z"


def test_an_unconfigured_client_raises():
    with pytest.raises(OpenCostException, match="not configured"):
        OpenCostClient("").fetch_allocations(
            datetime(2026, 9, 23, 8), datetime(2026, 9, 23, 9)
        )
