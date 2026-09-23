"""The ledger write is append-only and idempotent."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from sqlmodel import select

from app.models import UsageSampleORM
from app.services.usage import ledger
from app.services.usage.ledger import SampleRow
from tests.usage_fixtures import seeded_catalog, subject  # noqa: F401

pytestmark = pytest.mark.usefixtures("seeded_catalog")

WINDOW = datetime(2026, 9, 23, 13, 0, 0)
OBSERVED = datetime(2026, 9, 23, 14, 5, 0)


def _rows(subject_id: int) -> list[SampleRow]:
    return [
        SampleRow(
            subject_id=subject_id,
            metric="cpu_core_hours",
            window_start=WINDOW,
            interval_seconds=3600,
            value=Decimal("0.00009"),
        ),
        SampleRow(
            subject_id=subject_id,
            metric="ram_byte_hours",
            window_start=WINDOW,
            interval_seconds=3600,
            value=Decimal("123456789"),
        ),
    ]


def test_the_catalog_is_readable_by_name(db_session):
    catalog = ledger.metric_ids(db_session)
    assert "cpu_core_hours" in catalog
    assert "running_seconds" in catalog


def test_a_batch_is_recorded(db_session, subject):
    inserted = ledger.record_samples(
        db_session, _rows(subject.id), observed_at=OBSERVED
    )
    db_session.commit()

    assert inserted == 2
    stored = db_session.exec(select(UsageSampleORM)).all()
    assert len(stored) == 2
    assert {s.value for s in stored} == {Decimal("0.00009"), Decimal("123456789")}


def test_a_fractional_value_is_stored_exactly(db_session, subject):
    """`numeric`, not a float with an invented scale factor."""
    ledger.record_samples(
        db_session,
        [
            SampleRow(
                subject_id=subject.id,
                metric="cpu_core_hours",
                window_start=WINDOW,
                interval_seconds=3600,
                value=Decimal("0.000090000001"),
            )
        ],
        observed_at=OBSERVED,
    )
    db_session.commit()

    stored = db_session.exec(select(UsageSampleORM)).one()
    assert stored.value == Decimal("0.000090000001")


def test_replaying_a_recorded_window_changes_nothing_and_raises_nothing(
    db_session, subject
):
    ledger.record_samples(db_session, _rows(subject.id), observed_at=OBSERVED)
    db_session.commit()

    replayed = [
        SampleRow(
            subject_id=row.subject_id,
            metric=row.metric,
            window_start=row.window_start,
            interval_seconds=row.interval_seconds,
            value=row.value * 99,
        )
        for row in _rows(subject.id)
    ]
    inserted = ledger.record_samples(
        db_session, replayed, observed_at=datetime(2026, 9, 24, 9, 0, 0)
    )
    db_session.commit()

    assert inserted == 0
    stored = db_session.exec(select(UsageSampleORM)).all()
    assert len(stored) == 2
    assert {s.value for s in stored} == {Decimal("0.00009"), Decimal("123456789")}
    assert {s.observed_at for s in stored} == {OBSERVED}


def test_a_partly_recorded_batch_inserts_only_what_is_missing(db_session, subject):
    rows = _rows(subject.id)
    ledger.record_samples(db_session, rows[:1], observed_at=OBSERVED)
    db_session.commit()

    inserted = ledger.record_samples(db_session, rows, observed_at=OBSERVED)
    db_session.commit()

    assert inserted == 1
    assert len(db_session.exec(select(UsageSampleORM)).all()) == 2


def test_an_uncatalogued_metric_raises_rather_than_being_dropped(db_session, subject):
    with pytest.raises(KeyError, match="cpu_nanocores"):
        ledger.record_samples(
            db_session,
            [
                SampleRow(
                    subject_id=subject.id,
                    metric="cpu_nanocores",
                    window_start=WINDOW,
                    interval_seconds=3600,
                    value=Decimal("1"),
                )
            ],
            observed_at=OBSERVED,
        )


def test_an_empty_batch_is_a_no_op(db_session):
    assert ledger.record_samples(db_session, [], observed_at=OBSERVED) == 0
