"""Writing to the usage ledger: append-only and idempotent.

``ON CONFLICT DO NOTHING`` against the natural primary key, so the check and the
insert are one statement and a concurrent writer cannot slip between them. ``DO
NOTHING`` rather than ``DO UPDATE`` because a second observation of a window is a
duplicate, not a correction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, select

from app.models import UsageMetricORM, UsageSampleORM

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SampleRow:
    """One value to record, naming its metric by catalog name."""

    subject_id: int
    metric: str
    window_start: datetime
    interval_seconds: int
    value: Decimal


def metric_ids(session: Session) -> dict[str, int]:
    """The catalog, by name. The sampler caches it per pass."""
    return {
        row.name: row.id for row in session.exec(select(UsageMetricORM)).all()
    }


def record_samples(
    session: Session,
    rows: list[SampleRow],
    *,
    observed_at: datetime,
    catalog: dict[str, int] | None = None,
) -> int:
    """Record a batch, skipping what is already there. Returns rows inserted.

    An unknown metric name raises rather than being dropped: writing fewer quantities
    than intended is the failure this ledger exists to avoid.
    """
    if not rows:
        return 0

    catalog = catalog if catalog is not None else metric_ids(session)
    unknown = sorted({row.metric for row in rows} - catalog.keys())
    if unknown:
        raise KeyError(f"uncatalogued metric(s): {', '.join(unknown)}")

    values = [
        {
            "subject_id": row.subject_id,
            "metric_id": catalog[row.metric],
            "window_start": row.window_start,
            "interval_seconds": row.interval_seconds,
            "observed_at": observed_at,
            "value": row.value,
        }
        for row in rows
    ]

    statement = insert(UsageSampleORM.__table__).values(values)
    # RETURNING rather than `rowcount`, which this driver reports as -1 here.
    inserted = session.execute(
        statement.on_conflict_do_nothing(
            index_elements=["subject_id", "metric_id", "window_start"]
        ).returning(UsageSampleORM.__table__.c.window_start)
    ).all()
    return len(inserted)
