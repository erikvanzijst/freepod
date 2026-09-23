"""Migration coverage for the usage ledger tables, view and catalog seed.

Each run migrates a throwaway schema (via ``PGOPTIONS=-csearch_path=...``) so it
never touches the tables the rest of the suite or a local dev database relies
on, following ``test_migration_namespace_unique``.

Alembic is driven as a subprocess: the repo's own ``alembic/`` package shadows
the installed ``alembic`` distribution whenever the project root is on
``sys.path``, which it always is under pytest.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from tests.conftest import TEST_DATABASE_URL
from tests.usage_fixtures import CATALOG


API_ROOT = Path(__file__).resolve().parents[1]
BEFORE_LEDGER = "f3a4b5c6d7e8"
LEDGER = "b5c6d7e8f9a0"


def _alembic(*args: str, schema: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(Path(sys.executable).parent / "alembic"), *args],
        cwd=API_ROOT,
        env={
            **os.environ,
            "CAELUS_DATABASE_URL": TEST_DATABASE_URL,
            "PGOPTIONS": f"-csearch_path={schema}",
        },
        capture_output=True,
        text=True,
    )


def _run(*args: str, schema: str) -> None:
    result = _alembic(*args, schema=schema)
    assert result.returncode == 0, f"alembic {' '.join(args)} failed:\n{result.stderr}"


@pytest.fixture
def schema():
    name = f"mig_usage_{uuid4().hex[:8]}"
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{name}"'))
    try:
        yield name
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{name}" CASCADE'))


def _engine(schema: str):
    return create_engine(
        TEST_DATABASE_URL, connect_args={"options": f"-csearch_path={schema}"}
    )


def test_upgrade_creates_tables_and_downgrade_removes_them(schema):
    _run("upgrade", LEDGER, schema=schema)
    engine = _engine(schema)
    with engine.begin() as conn:
        present = set(
            conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = :s"
                ),
                {"s": schema},
            ).scalars()
        )
    assert {"usage_metric", "usage_subject", "usage_sample", "usage_amount"} <= present

    _run("downgrade", BEFORE_LEDGER, schema=schema)
    with engine.begin() as conn:
        remaining = set(
            conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = :s"
                ),
                {"s": schema},
            ).scalars()
        )
    assert not {
        "usage_metric",
        "usage_subject",
        "usage_sample",
        "usage_amount",
    } & remaining


def test_catalog_is_seeded_by_the_migration(schema):
    """Seeded here rather than by the worker, so there is no window in which an
    uncatalogued quantity is writable."""
    _run("upgrade", LEDGER, schema=schema)
    with _engine(schema).begin() as conn:
        rows = {
            name: (axis, unit, kind, role)
            for name, axis, unit, kind, role in conn.execute(
                text("SELECT name, axis, unit, kind, role FROM usage_metric")
            )
        }

    assert rows["cpu_core_hours"] == ("cpu", "core_hours", "delta", "usage")
    assert rows["ram_byte_hours"] == ("memory", "byte_hours", "delta", "usage")
    assert rows["cpu_request_cores_avg"] == ("cpu", "cores", "gauge", "allocation")
    assert rows["running_seconds"] == ("runtime", "seconds", "delta", "usage")
    assert rows["pv_byte_hours"] == ("storage", "byte_hours", "delta", "allocation")
    assert {"cpu_usage_cores_avg", "cpu_limit_cores_avg"} <= rows.keys()
    assert {"ram_usage_bytes_avg", "ram_limit_bytes_avg"} <= rows.keys()
    assert {"network_transmit_bytes", "network_receive_bytes"} <= rows.keys()


def test_the_test_catalog_matches_what_the_migration_seeds(schema):
    """`usage_fixtures.CATALOG` re-seeds what the per-test reset empties. It is a
    second copy of the migration's list, so it is pinned to it here."""
    _run("upgrade", LEDGER, schema=schema)
    with _engine(schema).begin() as conn:
        seeded = conn.execute(
            text("SELECT name, axis, unit, kind, role FROM usage_metric ORDER BY id")
        ).all()

    assert [tuple(row) for row in seeded] == CATALOG


def test_an_uncatalogued_quantity_cannot_be_written(schema):
    _run("upgrade", LEDGER, schema=schema)
    engine = _engine(schema)
    with engine.begin() as conn:
        subject_id = conn.execute(
            text(
                "INSERT INTO usage_subject (kind, ref, namespace, first_seen_at, "
                "last_seen_at) VALUES ('container', 'ns/Deployment/app/web', 'ns', "
                "now(), now()) RETURNING id"
            )
        ).scalar_one()
        unused = conn.execute(
            text("SELECT max(id) + 1 FROM usage_metric")
        ).scalar_one()

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO usage_sample (subject_id, metric_id, window_start, "
                    "interval_seconds, observed_at, value) "
                    "VALUES (:s, :m, '2026-09-23 13:00:00', 3600, now(), 1)"
                ),
                {"s": subject_id, "m": unused},
            )


def test_the_view_makes_both_kinds_additive(schema):
    """A gauge is multiplied by the window; a delta is taken as recorded."""
    _run("upgrade", LEDGER, schema=schema)
    engine = _engine(schema)
    with engine.begin() as conn:
        subject_id = conn.execute(
            text(
                "INSERT INTO usage_subject (kind, ref, first_seen_at, last_seen_at) "
                "VALUES ('container', 'ns/Deployment/app/web', now(), now()) "
                "RETURNING id"
            )
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO usage_sample (subject_id, metric_id, window_start, "
                "interval_seconds, observed_at, value) "
                "SELECT :s, id, '2026-09-23 13:00:00', 3600, now(), 2 "
                "FROM usage_metric WHERE name IN "
                "('cpu_core_hours', 'cpu_usage_cores_avg')"
            ),
            {"s": subject_id},
        )
        amounts = dict(
            conn.execute(
                text("SELECT metric, amount FROM usage_amount WHERE subject_id = :s"),
                {"s": subject_id},
            ).all()
        )

    assert amounts["cpu_core_hours"] == 2
    assert amounts["cpu_usage_cores_avg"] == 2 * 3600
