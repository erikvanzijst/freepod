"""Migration coverage for build usage: builds already finished are marked recorded.

Follows ``test_migration_build_deployment``: a throwaway schema migrated to the
revision before this one, seeded by hand, then upgraded and inspected.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text

from tests.conftest import TEST_DATABASE_URL
from tests.test_migration_build_deployment import _deployment, _user
from tests.test_migration_namespace_unique import _upgrade

BEFORE = "da4841625b1f"
USAGE = "9df604f2b702"

USAGE_COLUMNS = {
    "usage_cpu_seconds",
    "usage_memory_byte_seconds",
    "usage_memory_peak_bytes",
    "usage_started_at",
    "usage_finished_at",
    "usage_recorded_at",
}


@pytest.fixture
def migrated_schema():
    """A throwaway schema at the revision before builds recorded their usage."""
    schema = f"mig_buildusage_{uuid4().hex[:8]}"
    admin = create_engine(TEST_DATABASE_URL)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        _upgrade("upgrade", BEFORE, schema=schema)
        yield schema, create_engine(
            TEST_DATABASE_URL, connect_args={"options": f"-csearch_path={schema}"}
        )
    finally:
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


def _build(conn, deployment_id: UUID, status: str) -> UUID:
    build_id = uuid4()
    conn.execute(
        text(
            "INSERT INTO build (id, deployment_id, artifact_id, status, created_at, log) "
            "VALUES (:id, :d, :a, :s, now(), '')"
        ),
        {"id": build_id, "d": deployment_id, "a": uuid4().hex, "s": status},
    )
    return build_id


def _columns(conn, schema: str) -> set[str]:
    return set(
        conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = :s AND table_name = 'build'"
            ),
            {"s": schema},
        ).scalars()
    )


def test_finished_builds_are_marked_recorded_and_open_ones_are_not(migrated_schema):
    schema, engine = migrated_schema
    with engine.begin() as conn:
        deployment = _deployment(conn, _user(conn))
        finished = {
            status: _build(conn, deployment, status)
            for status in ("succeeded", "failed", "canceled")
        }
        open_ = {status: _build(conn, deployment, status) for status in ("queued", "running")}

    _upgrade("upgrade", USAGE, schema=schema)

    with engine.begin() as conn:
        recorded = dict(
            conn.execute(text("SELECT id, usage_recorded_at IS NOT NULL FROM build")).all()
        )
        # Marked, but with nothing measured: the marker alone keeps them out.
        measured = conn.execute(
            text("SELECT count(*) FROM build WHERE usage_cpu_seconds IS NOT NULL")
        ).scalar_one()
    assert all(recorded[b] for b in finished.values())
    assert not any(recorded[b] for b in open_.values())
    assert measured == 0


def test_the_downgrade_round_trips(migrated_schema):
    schema, engine = migrated_schema
    with engine.begin() as conn:
        build = _build(conn, _deployment(conn, _user(conn)), "succeeded")

    _upgrade("upgrade", USAGE, schema=schema)
    with engine.begin() as conn:
        assert USAGE_COLUMNS <= _columns(conn, schema)

    _upgrade("downgrade", BEFORE, schema=schema)
    with engine.begin() as conn:
        assert not USAGE_COLUMNS & _columns(conn, schema)
        assert conn.execute(text("SELECT id FROM build")).scalar_one() == build

    _upgrade("upgrade", USAGE, schema=schema)
