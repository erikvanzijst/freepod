"""A window is read, or it is refused — and all three refusals look alike.

The point of the uniformity: the caller must record nothing and advance nothing in
every case, so there is no branch for it to get wrong.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app.services.usage.opencost import OpenCostClient
from app.services.usage.source import billable, read_window

FIXTURES = Path(__file__).parent / "fixtures"
START = datetime(2026, 9, 23, 10)
END = datetime(2026, 9, 23, 11)

COVERED = {"data": {"result": [{"metric": {}, "value": [1790161200, "126"]}]}}
UNCOVERED: dict = {"data": {"result": []}}


def _client(*, cover, allocation_status=200, allocation_body=None) -> OpenCostClient:
    """Routes the presence check and the allocation fetch to separate answers."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "/api/v1/query" in request.url.path:
            return httpx.Response(200, json=COVERED if cover else UNCOVERED)
        if allocation_status != 200:
            return httpx.Response(allocation_status)
        return httpx.Response(
            allocation_status,
            content=allocation_body,
            headers={"content-type": "application/json"},
        )

    return OpenCostClient(
        "http://opencost:9003",
        prometheus_url="http://prometheus",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


@pytest.fixture
def healthy_body() -> str:
    return (FIXTURES / "opencost_allocation.json").read_text()


def test_a_covered_window_yields_its_allocations(healthy_body):
    client = _client(cover=True, allocation_body=healthy_body)
    result = read_window(client, START, END)
    assert result.is_usable
    assert result.allocations
    assert result.interval_seconds == 3600


def test_an_uncovered_window_yields_nothing(healthy_body):
    """The failure that answers 200 with plausible numbers."""
    result = read_window(_client(cover=False, allocation_body=healthy_body), START, END)
    assert not result.is_usable
    assert result.allocations is None
    assert "exporter" in result.reason


def test_a_non_200_yields_nothing():
    result = read_window(_client(cover=True, allocation_status=503), START, END)
    assert not result.is_usable
    assert result.allocations is None
    assert "503" in result.reason


def test_an_empty_result_set_yields_nothing():
    empty = json.dumps({"code": 200, "data": [{}]})
    result = read_window(_client(cover=True, allocation_body=empty), START, END)
    assert not result.is_usable
    assert result.allocations is None
    assert "no allocations" in result.reason


def test_a_missing_data_key_yields_nothing():
    result = read_window(
        _client(cover=True, allocation_body=json.dumps({"code": 200})), START, END
    )
    assert not result.is_usable


def test_every_refusal_is_reported_the_same_way(healthy_body):
    """No caller branch can treat one refusal differently from another."""
    refusals = [
        read_window(_client(cover=False, allocation_body=healthy_body), START, END),
        read_window(_client(cover=True, allocation_status=503), START, END),
        read_window(
            _client(cover=True, allocation_body=json.dumps({"code": 200, "data": [{}]})),
            START,
            END,
        ),
    ]
    assert all(r.allocations is None for r in refusals)
    assert all(not r.is_usable for r in refusals)
    assert all(r.reason for r in refusals)


def test_an_unreachable_source_yields_nothing_rather_than_raising():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    client = OpenCostClient(
        "http://opencost:9003",
        prometheus_url="http://prometheus",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = read_window(client, START, END)
    assert not result.is_usable
    assert result.allocations is None


def test_a_refused_window_offers_no_quantities_to_write(healthy_body):
    """There is nothing a caller could write even if it tried."""
    result = read_window(_client(cover=False, allocation_body=healthy_body), START, END)
    assert result.allocations is None
    with pytest.raises(TypeError):
        billable(result.allocations, environment="dev")


def test_unmounted_buckets_are_dropped_before_recording(healthy_body):
    result = read_window(_client(cover=True, allocation_body=healthy_body), START, END)
    kept = billable(result.allocations, environment="dev")
    assert kept
    assert not any(a.is_unmounted for a in kept)
    assert any(a.is_unmounted for a in result.allocations)


def test_the_exporter_check_runs_before_the_fetch():
    """An untrustworthy window costs no allocation request."""
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if "/api/v1/query" in request.url.path:
            return httpx.Response(200, json=UNCOVERED)
        return httpx.Response(200, json={"code": 200, "data": []})

    client = OpenCostClient(
        "http://opencost:9003",
        prometheus_url="http://prometheus",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    read_window(client, START, END)
    assert paths == ["/api/v1/query"]


def test_values_survive_the_read_as_exact_decimals(healthy_body):
    result = read_window(_client(cover=True, allocation_body=healthy_body), START, END)
    values = [v for a in result.allocations for v in a.fields.values()]
    assert values
    assert all(isinstance(v, Decimal) for v in values)


def _allocations(body):
    return read_window(_client(cover=True, allocation_body=body), START, END).allocations


def test_a_foreign_environments_tenant_is_skipped(healthy_body):
    """The same container would otherwise land in two ledgers, attributed in one."""
    kept = billable(_allocations(healthy_body), environment="dev")
    assert not [a for a in kept if a.tenant_environment == "prod"]
    assert [a for a in _allocations(healthy_body) if a.tenant_environment == "prod"]


def test_our_own_tenants_are_kept(healthy_body):
    kept = billable(_allocations(healthy_body), environment="dev")
    ours = [a for a in kept if a.is_tenant]
    assert ours
    assert {a.tenant_environment for a in ours} == {"dev"}


def test_platform_workloads_are_kept_by_every_environment(healthy_body):
    """No single environment owns them, so each records them."""
    platform = [a for a in billable(_allocations(healthy_body), environment="dev")
                if not a.is_tenant]
    assert platform
    for environment in ("dev", "prod"):
        kept = billable(_allocations(healthy_body), environment=environment)
        assert {a.namespace for a in kept if not a.is_tenant} == {
            a.namespace for a in platform
        }


def test_a_tenant_with_no_environment_label_is_kept(healthy_body):
    """A missing label must not silently drop real usage."""
    from dataclasses import replace

    tenant = next(a for a in _allocations(healthy_body) if a.is_tenant)
    unlabelled = replace(
        tenant,
        namespace_labels={k: v for k, v in tenant.namespace_labels.items()
                          if not k.endswith("_environment")},
    )
    assert unlabelled.tenant_environment is None
    assert billable([unlabelled], environment="dev") == [unlabelled]


def test_the_filter_is_symmetric(healthy_body):
    """Run as prod, the dev tenants are what gets skipped."""
    kept = billable(_allocations(healthy_body), environment="prod")
    assert not [a for a in kept if a.tenant_environment == "dev"]
    assert [a for a in kept if a.tenant_environment == "prod"]


def _in_namespace(body, namespace: str):
    from dataclasses import replace

    platform = next(a for a in _allocations(body) if not a.is_tenant)
    return replace(platform, namespace=namespace)


def test_our_own_builds_namespace_is_skipped(healthy_body):
    """The build worker records those builds from their own measurements."""
    build = _in_namespace(healthy_body, "caelus-builds-dev")

    assert billable([build], environment="dev", builds_namespace="caelus-builds-dev") == []


def test_another_environments_builds_namespace_is_platform_overhead(healthy_body):
    build = _in_namespace(healthy_body, "caelus-builds")

    assert billable([build], environment="dev", builds_namespace="caelus-builds-dev") == [build]
    assert not build.is_tenant
