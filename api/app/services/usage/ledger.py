"""Writing to the usage ledger: append-only and idempotent, in bounded chunks.

``ON CONFLICT DO NOTHING`` against the natural primary key, so the check and the
insert are one statement and a concurrent writer cannot slip between them. ``DO
NOTHING`` rather than ``DO UPDATE`` because a second observation of a window is a
duplicate, not a correction.

Everything here consumes iterables a chunk at a time, so what a source yields is never
held whole: memory stays bounded by the chunk size however many subjects a window has.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, select

from app.models import UsageMetricORM, UsageSampleORM
from app.services.usage.batching import CHUNK_SIZE, batched
from app.services.usage.subjects import SubjectSpec, upsert_subjects

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class SampleRow:
    """One value to record, naming its metric by catalog name."""

    subject_id: int
    metric: str
    window_start: datetime
    interval_seconds: int
    value: Decimal


@dataclass(frozen=True)
class Observation:
    """What a source measured for one subject over one window, before it has an id."""

    subject: SubjectSpec
    quantities: Mapping[str, Decimal]


def metric_ids(session: Session) -> dict[str, int]:
    """The catalog, by name. The sampler caches it per pass."""
    return {
        row.name: row.id for row in session.exec(select(UsageMetricORM)).all()
    }


def record_samples(
    session: Session,
    rows: Iterable[SampleRow],
    *,
    observed_at: datetime,
    catalog: dict[str, int] | None = None,
    chunk_size: int = CHUNK_SIZE,
) -> int:
    """Record samples a chunk at a time, skipping what is already there. Returns rows
    inserted.

    An unknown metric name raises rather than being dropped: writing fewer quantities
    than intended is the failure this ledger exists to avoid. Chunks before it may have
    been written; the caller's rollback discards them with the rest of the window.
    """
    catalog = catalog if catalog is not None else metric_ids(session)
    inserted = 0
    for chunk in batched(rows, chunk_size):
        unknown = sorted({row.metric for row in chunk} - catalog.keys())
        if unknown:
            raise KeyError(f"uncatalogued metric(s): {', '.join(unknown)}")

        statement = insert(UsageSampleORM.__table__).values(
            [
                {
                    "subject_id": row.subject_id,
                    "metric_id": catalog[row.metric],
                    "window_start": row.window_start,
                    "interval_seconds": row.interval_seconds,
                    "observed_at": observed_at,
                    "value": row.value,
                }
                for row in chunk
            ]
        )
        # RETURNING rather than `rowcount`, which this driver reports as -1 here.
        inserted += len(
            session.execute(
                statement.on_conflict_do_nothing(
                    index_elements=["subject_id", "metric_id", "window_start"]
                ).returning(UsageSampleORM.__table__.c.window_start)
            ).all()
        )
    return inserted


def record_observations(
    session: Session,
    observations: Iterable[Observation],
    *,
    window_start: datetime,
    interval_seconds: int,
    observed_at: datetime,
    catalog: dict[str, int] | None = None,
    chunk_size: int = CHUNK_SIZE,
) -> int:
    """Record one window's observations: each chunk's subjects in one upsert, then its
    samples. Returns samples inserted. Does not commit.
    """
    catalog = catalog if catalog is not None else metric_ids(session)
    inserted = 0
    for chunk in batched(observations, chunk_size):
        ids = upsert_subjects(
            session, (o.subject for o in chunk), observed_at=observed_at
        )
        inserted += record_samples(
            session,
            (
                SampleRow(
                    subject_id=ids[o.subject.key],
                    metric=metric,
                    window_start=window_start,
                    interval_seconds=interval_seconds,
                    value=value,
                )
                for o in chunk
                for metric, value in o.quantities.items()
            ),
            observed_at=observed_at,
            catalog=catalog,
            chunk_size=chunk_size,
        )
    return inserted
