"""Migration coverage for the usage rate table and its seed.

Follows ``test_migration_usage_ledger``: each run migrates a throwaway schema, and
alembic runs as a subprocess.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import text

from tests.test_migration_usage_ledger import LEDGER, _engine, _run, schema  # noqa: F401

RATES = "c6d7e8f9a0b1"


def test_the_migration_seeds_the_billable_rates(schema):
    _run("upgrade", RATES, schema=schema)
    with _engine(schema).begin() as conn:
        rows = {
            name: (unit_price, per_quantity)
            for name, unit_price, per_quantity in conn.execute(
                text(
                    "SELECT m.name, r.unit_price, r.per_quantity "
                    "FROM usage_rate r JOIN usage_metric m ON m.id = r.metric_id"
                )
            )
        }

    # The OpenCost costModel's figures: CPU per core-hour, RAM per GiB-hour.
    assert rows == {
        "cpu_core_hours": (Decimal("0.015437"), Decimal(1)),
        "ram_byte_hours": (Decimal("0.002069"), Decimal(2**30)),
    }


def test_downgrade_drops_the_rates_and_keeps_the_ledger(schema):
    _run("upgrade", RATES, schema=schema)
    _run("downgrade", LEDGER, schema=schema)
    with _engine(schema).begin() as conn:
        present = set(
            conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = :s"
                ),
                {"s": schema},
            ).scalars()
        )
    assert "usage_rate" not in present
    assert {"usage_metric", "usage_sample"} <= present
