"""The ledger's write path at scale: bounded chunks, one statement each, lazily consumed.

Counts the statements actually sent, so a regression to per-row writes or to
materializing a source's output fails here rather than in production.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlmodel import select

from app.models import UsageSampleORM, UsageSubjectORM
from app.models.usage import SubjectKind
from app.services import relational_storage
from app.services.usage.batching import batched
from app.services.usage.ledger import Observation, SampleRow, record_observations, record_samples
from app.services.usage.subjects import SubjectSpec, upsert_subjects
from tests.test_usage_databases import FakePrometheus, _deployment_with_database
from tests.usage_fixtures import seeded_catalog  # noqa: F401

WINDOW = datetime(2026, 10, 6, 13)
OBSERVED = datetime(2026, 10, 6, 14, 30)


@contextmanager
def statements(session) -> Iterator[list[str]]:
    """Every SQL statement the session sends inside the block."""
    sent: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        sent.append(statement)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        yield sent
    finally:
        event.remove(engine, "before_cursor_execute", record)


def _count(sent: list[str], prefix: str) -> int:
    return sum(1 for statement in sent if statement.lstrip().upper().startswith(prefix))


def test_batched_chunks_without_materializing():
    pulled = []

    def numbers():
        for n in range(5):
            pulled.append(n)
            yield n

    chunks = batched(numbers(), 2)
    assert next(chunks) == (0, 1)
    assert pulled == [0, 1], "only the first chunk has been drawn"
    assert list(chunks) == [(2, 3), (4,)]


def test_subjects_are_upserted_one_statement_per_chunk(db_session):
    specs = [SubjectSpec(kind=SubjectKind.DATABASE, ref=f"dpl_{n}") for n in range(5)]
    with statements(db_session) as sent:
        ids = upsert_subjects(db_session, specs, observed_at=OBSERVED, chunk_size=2)
    db_session.commit()

    assert _count(sent, "INSERT INTO USAGE_SUBJECT") == 3
    assert set(ids) == {("database", f"dpl_{n}") for n in range(5)}
    assert len(set(ids.values())) == 5


def test_duplicates_within_a_chunk_are_merged_keeping_the_deployment(db_session):
    """PostgreSQL refuses to upsert one row twice in a statement."""
    deployment_id = _deployment_with_database(db_session).id
    specs = [
        SubjectSpec(kind=SubjectKind.CONTAINER, ref="ns/a/b/c", namespace="ns"),
        SubjectSpec(
            kind=SubjectKind.CONTAINER, ref="ns/a/b/c", namespace="ns", deployment_id=deployment_id
        ),
    ]
    ids = upsert_subjects(db_session, specs, observed_at=OBSERVED)
    db_session.commit()

    subject = db_session.get(UsageSubjectORM, ids[("container", "ns/a/b/c")])
    assert subject.deployment_id == deployment_id


def test_samples_are_inserted_one_statement_per_chunk(db_session, seeded_catalog):
    subject_id = upsert_subjects(
        db_session, [SubjectSpec(kind=SubjectKind.DATABASE, ref="dpl_x")], observed_at=OBSERVED
    )[("database", "dpl_x")]
    rows = (
        SampleRow(
            subject_id=subject_id,
            metric="db_byte_hours",
            window_start=datetime(2026, 10, 6, hour),
            interval_seconds=3600,
            value=Decimal(1),
        )
        for hour in range(5)
    )
    with statements(db_session) as sent:
        written = record_samples(db_session, rows, observed_at=OBSERVED, chunk_size=2)

    assert written == 5
    assert _count(sent, "INSERT INTO USAGE_SAMPLE") == 3


def test_observations_are_consumed_a_chunk_at_a_time(db_session, seeded_catalog):
    """The source's generator is never drained ahead of what has been written."""
    drawn = []

    def observations():
        for n in range(5):
            drawn.append(n)
            yield Observation(
                subject=SubjectSpec(kind=SubjectKind.DATABASE, ref=f"dpl_{n}"),
                quantities={"db_byte_hours": Decimal(n)},
            )

    seen_at_first_write = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("INSERT INTO USAGE_SUBJECT") and not seen_at_first_write:
            seen_at_first_write.append(len(drawn))

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        written = record_observations(
            db_session,
            observations(),
            window_start=WINDOW,
            interval_seconds=3600,
            observed_at=OBSERVED,
            chunk_size=2,
        )
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert written == 5
    assert seen_at_first_write == [2], "the first write happened after one chunk was drawn"


def test_database_attribution_is_one_query_per_chunk_however_many_are_measured(
    db_session, seeded_catalog, monkeypatch
):
    """No per-database lookups: the join to the platform's records is set-based."""
    monkeypatch.setattr("app.services.usage.databases.batched", lambda items: batched(items, 2))
    known = [_deployment_with_database(db_session) for _ in range(3)]
    names = [relational_storage.database_name(d) for d in known]
    unknown = [f"dpl_{uuid4().hex}" for _ in range(2)]
    source = FakePrometheus(sizes=lambda end: {n: 2**30 for n in names + unknown}).source()

    observed = source.read(db_session, WINDOW, window_seconds=3600)
    with statements(db_session) as sent:
        written = record_observations(
            db_session, observed, window_start=WINDOW, interval_seconds=3600, observed_at=OBSERVED
        )
    db_session.commit()

    # Five measured names in chunks of two: three joins, and no per-database reads.
    joins = [q for q in sent if "deployment_database" in q]
    assert len(joins) == 3
    assert all("unnest" in q for q in joins)
    assert not any("FROM subscription" in q or "FROM plan_template_version" in q for q in sent)
    # Three known databases, each with its size and its plan's allowance.
    assert written == 6
    refs = {s.ref for s in db_session.exec(select(UsageSubjectORM)).all()}
    assert refs == set(names)
    assert len(db_session.exec(select(UsageSampleORM)).all()) == 6


@pytest.mark.parametrize("chunk_size", [1, 1000])
def test_chunk_size_does_not_change_what_is_recorded(db_session, seeded_catalog, chunk_size):
    def observations():
        for n in range(3):
            yield Observation(
                subject=SubjectSpec(kind=SubjectKind.DATABASE, ref=f"dpl_{n}"),
                quantities={"db_byte_hours": Decimal(n), "db_allowance_byte_hours": Decimal(9)},
            )

    written = record_observations(
        db_session,
        observations(),
        window_start=WINDOW,
        interval_seconds=3600,
        observed_at=OBSERVED,
        chunk_size=chunk_size,
    )
    assert written == 6


def test_container_attribution_is_one_query_per_chunk(db_session, monkeypatch):
    """OpenCost's allocations are attributed by namespace a chunk at a time."""
    from app.services.usage import containers
    from tests.test_usage_subjects import _allocation

    monkeypatch.setattr(containers, "batched", lambda items: batched(items, 2))
    allocations = [_allocation(namespace=f"ns-{n}") for n in range(5)]
    with statements(db_session) as sent:
        observed = list(containers.observations(db_session, allocations))

    assert len(observed) == 5
    assert len([q for q in sent if "FROM deployment" in q]) == 3
