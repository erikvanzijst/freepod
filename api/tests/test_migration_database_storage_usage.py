"""Migration coverage for the database storage metrics and their rate.

Follows ``test_migration_usage_rate``: each run migrates a throwaway schema, and alembic
runs as a subprocess.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import text

from tests.test_migration_usage_ledger import _engine, _run, schema  # noqa: F401

BEFORE = "d71152c7e6ff"
STORAGE = "4b7e2c9d1a36"


def _metrics(conn) -> dict[str, tuple[str, str, str, str]]:
    return {
        name: (axis, unit, kind, role)
        for name, axis, unit, kind, role in conn.execute(
            text(
                "SELECT name, axis, unit, kind, role FROM usage_metric "
                "WHERE name LIKE 'db\\_%'"
            )
        )
    }


def test_the_migration_catalogs_size_and_allowance_and_prices_size(schema):
    _run("upgrade", STORAGE, schema=schema)
    with _engine(schema).begin() as conn:
        metrics = _metrics(conn)
        rates = conn.execute(
            text(
                "SELECT m.name, r.effective_from, r.unit_price, r.per_quantity "
                "FROM usage_rate r JOIN usage_metric m ON m.id = r.metric_id "
                "WHERE m.name LIKE 'db\\_%'"
            )
        ).all()

    assert metrics == {
        "db_byte_hours": ("storage", "byte_hours", "delta", "usage"),
        "db_allowance_byte_hours": ("storage", "byte_hours", "delta", "allocation"),
    }
    # The allowance is recorded, never priced.
    assert [(name, str(start), price, per) for name, start, price, per in rates] == [
        ("db_byte_hours", "2026-10-06 00:00:00", Decimal("0.000171"), Decimal(2**30))
    ]


def test_downgrade_removes_the_metrics_their_rate_and_samples(schema):
    _run("upgrade", STORAGE, schema=schema)
    with _engine(schema).begin() as conn:
        subject_id = conn.execute(
            text(
                "INSERT INTO usage_subject (kind, ref, first_seen_at, last_seen_at) "
                "VALUES ('database', 'dpl_x', now(), now()) RETURNING id"
            )
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO usage_sample "
                "(subject_id, metric_id, window_start, interval_seconds, observed_at, value) "
                "SELECT :s, id, '2026-10-06 13:00', 3600, now(), 1 FROM usage_metric "
                "WHERE name = 'db_byte_hours'"
            ),
            {"s": subject_id},
        )

    _run("downgrade", BEFORE, schema=schema)
    with _engine(schema).begin() as conn:
        assert _metrics(conn) == {}
        assert conn.execute(text("SELECT count(*) FROM usage_sample")).scalar_one() == 0
        # The at-cost rates are untouched.
        assert conn.execute(text("SELECT count(*) FROM usage_rate")).scalar_one() == 2


def test_the_fixture_catalog_matches_the_migration(schema):
    """`usage_fixtures` seeds a second copy; a metric added to one alone fails here."""
    from tests.usage_fixtures import DATABASE_CATALOG

    _run("upgrade", STORAGE, schema=schema)
    with _engine(schema).begin() as conn:
        assert _metrics(conn) == {name: tuple(rest) for name, *rest in DATABASE_CATALOG}


INDEX = "5c8f3d0e2b47"


def _indexes(conn) -> dict[str, str]:
    return dict(
        conn.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'deployment_database' AND schemaname = current_schema()")
        ).all()
    )


def test_db_name_gets_a_unique_index_and_loses_it_on_downgrade(schema):
    _run("upgrade", INDEX, schema=schema)
    with _engine(schema).begin() as conn:
        definition = _indexes(conn)["uq_deployment_database_db_name"]
    assert "UNIQUE" in definition and "(db_name)" in definition

    _run("downgrade", STORAGE, schema=schema)
    with _engine(schema).begin() as conn:
        assert "uq_deployment_database_db_name" not in _indexes(conn)
