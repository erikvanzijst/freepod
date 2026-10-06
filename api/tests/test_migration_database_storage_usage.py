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
