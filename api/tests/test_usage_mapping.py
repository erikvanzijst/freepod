"""Each allocation becomes the catalogued quantities the design's mapping table names.

Driven by the recorded fixture rather than a hand-built allocation, so a change in
OpenCost's field names fails here rather than silently producing fewer quantities.
"""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.usage.opencost import parse_allocations
from app.services.usage.mapping import FIELD_METRICS, RUNNING_SECONDS, quantities
from tests.usage_fixtures import CATALOG

FIXTURES = Path(__file__).parent / "fixtures"

# (kind, role) per the design's mapping table, keyed by ledger metric.
EXPECTED_KIND_ROLE = {
    "cpu_core_hours": ("delta", "usage"),
    "cpu_usage_cores_avg": ("gauge", "usage"),
    "cpu_request_cores_avg": ("gauge", "allocation"),
    "cpu_limit_cores_avg": ("gauge", "allocation"),
    "ram_byte_hours": ("delta", "usage"),
    "ram_usage_bytes_avg": ("gauge", "usage"),
    "ram_request_bytes_avg": ("gauge", "allocation"),
    "ram_limit_bytes_avg": ("gauge", "allocation"),
    "network_transmit_bytes": ("delta", "usage"),
    "network_receive_bytes": ("delta", "usage"),
    "pv_byte_hours": ("delta", "allocation"),
    "running_seconds": ("delta", "usage"),
}


@pytest.fixture
def app_allocation():
    payload = json.loads(
        (FIXTURES / "opencost_allocation.json").read_text(), parse_float=Decimal
    )
    by_container = {a.container: a for a in parse_allocations(payload)[0]}
    return by_container["bookstack"]


def test_every_catalogued_quantity_is_produced(app_allocation):
    produced = quantities(app_allocation)
    assert set(produced) == set(FIELD_METRICS) | {RUNNING_SECONDS}


def test_each_quantity_has_the_kind_and_role_the_catalog_gives_it(app_allocation):
    catalog = {name: (kind, role) for name, _, _, kind, role in CATALOG}
    for metric in quantities(app_allocation):
        assert catalog[metric] == EXPECTED_KIND_ROLE[metric], metric


def test_the_mapping_names_only_catalogued_metrics():
    """A name that drifts out of the catalog fails the foreign key at write time."""
    catalogued = {name for name, *_ in CATALOG}
    assert set(FIELD_METRICS) | {RUNNING_SECONDS} <= catalogued


def test_the_billable_quantities_are_the_integrated_ones(app_allocation):
    """`cpuCoreHours` is max(request, usage) per container per minute, integrated --
    not something recomputed from the averages at invoice time."""
    produced = quantities(app_allocation)
    assert produced["cpu_core_hours"] == app_allocation.fields["cpuCoreHours"]
    assert produced["ram_byte_hours"] == app_allocation.fields["ramByteHours"]


def test_running_seconds_is_minutes_scaled_exactly(app_allocation):
    assert quantities(app_allocation)[RUNNING_SECONDS] == app_allocation.minutes * 60


def test_a_short_lived_container_is_distinguishable_from_a_quiet_one():
    """The reason runtime is recorded at all."""
    payload = json.loads(
        (FIXTURES / "opencost_allocation.json").read_text(), parse_float=Decimal
    )
    allocation = parse_allocations(payload)[0][0]
    short = quantities(replace(allocation, minutes=Decimal("11.43584")))
    assert short[RUNNING_SECONDS] == Decimal("686.1504")


def test_values_stay_exact_decimals(app_allocation):
    for metric, value in quantities(app_allocation).items():
        assert isinstance(value, Decimal), metric


def test_an_absent_field_produces_no_quantity(app_allocation):
    """Absent means not measured; a recorded zero means measured and zero."""
    stripped = {
        k: v for k, v in app_allocation.fields.items() if k != "networkTransferBytes"
    }
    produced = quantities(replace(app_allocation, fields=stripped))
    assert "network_transmit_bytes" not in produced
    assert "network_receive_bytes" in produced


def test_a_measured_zero_is_kept(app_allocation):
    """A container reporting no PV capacity measured zero; it is not absent."""
    zeroed = {**app_allocation.fields, "pvByteHours": Decimal(0)}
    assert quantities(replace(app_allocation, fields=zeroed))["pv_byte_hours"] == 0


def test_no_cost_field_is_consumed(app_allocation):
    """Cost is decided outside this record; the fields are present and ignored."""
    assert "cpuCost" in app_allocation.fields
    produced = quantities(app_allocation)
    assert not [m for m in produced if "cost" in m.lower()]
