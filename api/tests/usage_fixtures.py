"""Shared setup for the usage-ledger tests.

The catalog is seeded by the migration, but the suite's per-test reset empties
every table in `public`, so tests that need it re-seed it themselves. The list
below is a second copy of the migration's; ``test_migration_usage_ledger``
asserts the two agree, so a metric added to one and not the other fails the
suite rather than drifting silently.
"""

from __future__ import annotations

import pytest

from datetime import datetime
from decimal import Decimal

from sqlmodel import select

from app.models import UsageMetricORM, UsageRateORM, UsageSubjectORM

# (name, axis, unit, kind, role) -- mirrors METRICS in the migration.
CATALOG = [
    ("cpu_core_hours", "cpu", "core_hours", "delta", "usage"),
    ("cpu_usage_cores_avg", "cpu", "cores", "gauge", "usage"),
    ("cpu_request_cores_avg", "cpu", "cores", "gauge", "allocation"),
    ("cpu_limit_cores_avg", "cpu", "cores", "gauge", "allocation"),
    ("ram_byte_hours", "memory", "byte_hours", "delta", "usage"),
    ("ram_usage_bytes_avg", "memory", "bytes", "gauge", "usage"),
    ("ram_request_bytes_avg", "memory", "bytes", "gauge", "allocation"),
    ("ram_limit_bytes_avg", "memory", "bytes", "gauge", "allocation"),
    ("network_transmit_bytes", "network", "bytes", "delta", "usage"),
    ("network_receive_bytes", "network", "bytes", "delta", "usage"),
    ("pv_byte_hours", "storage", "byte_hours", "delta", "allocation"),
    ("running_seconds", "runtime", "seconds", "delta", "usage"),
]


@pytest.fixture
def seeded_catalog(db_session):
    """The metric catalog, as a freshly migrated database would have it."""
    for name, axis, unit, kind, role in CATALOG:
        db_session.add(
            UsageMetricORM(name=name, axis=axis, unit=unit, kind=kind, role=role)
        )
    db_session.commit()
    return CATALOG


@pytest.fixture
def subject(db_session) -> UsageSubjectORM:
    row = UsageSubjectORM(
        kind="container", ref="ns-a/Deployment/app/web", namespace="ns-a"
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


GIB = Decimal(2**30)

# Round numbers rather than the migration's real rates, so expected costs are
# legible in the assertions. (metric, effective_from, unit_price, per_quantity)
TEST_RATES = [
    ("cpu_core_hours", datetime(2026, 1, 1), Decimal("0.01"), Decimal(1)),
    ("ram_byte_hours", datetime(2026, 1, 1), Decimal("0.002"), GIB),
]


def add_rate(
    session,
    metric: str,
    effective_from: datetime,
    unit_price: Decimal,
    per_quantity: Decimal = Decimal(1),
) -> None:
    metric_id = session.exec(
        select(UsageMetricORM.id).where(UsageMetricORM.name == metric)
    ).one()
    session.add(
        UsageRateORM(
            metric_id=metric_id,
            effective_from=effective_from,
            unit_price=unit_price,
            per_quantity=per_quantity,
        )
    )
    session.commit()


@pytest.fixture
def seeded_rates(db_session, seeded_catalog):
    for rate in TEST_RATES:
        add_rate(db_session, *rate)
    return TEST_RATES
