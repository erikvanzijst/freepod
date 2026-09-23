"""Shared setup for the usage-ledger tests.

The catalog is seeded by the migration, but the suite's per-test reset empties
every table in `public`, so tests that need it re-seed it themselves. The list
below is a second copy of the migration's; ``test_migration_usage_ledger``
asserts the two agree, so a metric added to one and not the other fails the
suite rather than drifting silently.
"""

from __future__ import annotations

import pytest

from app.models import UsageMetricORM, UsageSubjectORM

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
