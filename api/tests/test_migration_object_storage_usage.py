"""Migration coverage for the resume-position index and the object storage metric.

Follows ``test_migration_database_storage_usage``: each run migrates a throwaway schema,
and alembic runs as a subprocess.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import text

from tests.test_migration_usage_ledger import _engine, _run, schema  # noqa: F401

BEFORE_INDEX = "5c8f3d0e2b47"
INDEX = "7d2e9f4a1c58"
STORAGE = "9e3b5a7c2d14"


def _indexes(conn) -> dict[str, str]:
    return dict(
        conn.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE tablename = 'usage_sample' AND schemaname = current_schema()"
            )
        ).all()
    )


def test_the_position_index_is_created_and_dropped(schema):
    _run("upgrade", INDEX, schema=schema)
    with _engine(schema).begin() as conn:
        definition = _indexes(conn)["ix_usage_sample_metric_window"]
    assert "(metric_id, window_start)" in definition

    _run("downgrade", BEFORE_INDEX, schema=schema)
    with _engine(schema).begin() as conn:
        assert "ix_usage_sample_metric_window" not in _indexes(conn)


def _metrics(conn) -> dict[str, tuple[str, str, str, str]]:
    return {
        name: (axis, unit, kind, role)
        for name, axis, unit, kind, role in conn.execute(
            text(
                "SELECT name, axis, unit, kind, role FROM usage_metric "
                "WHERE name LIKE 'object\\_storage\\_%'"
            )
        )
    }


def test_the_migration_catalogs_and_prices_object_storage(schema):
    _run("upgrade", STORAGE, schema=schema)
    with _engine(schema).begin() as conn:
        metrics = _metrics(conn)
        rates = conn.execute(
            text(
                "SELECT m.name, r.effective_from, r.unit_price, r.per_quantity "
                "FROM usage_rate r JOIN usage_metric m ON m.id = r.metric_id "
                "WHERE m.name LIKE 'object\\_storage\\_%'"
            )
        ).all()

    assert metrics == {
        "object_storage_byte_hours": ("storage", "byte_hours", "delta", "usage"),
    }
    assert [(name, str(start), price, per) for name, start, price, per in rates] == [
        ("object_storage_byte_hours", "2026-10-07 00:00:00", Decimal("0.0000274"), Decimal(2**30))
    ]
    # EUR 0.02 per GiB-month, rounded up to the rate's precision.
    assert rates[0][2] * 730 == Decimal("0.020002")


def test_downgrade_removes_the_metric_its_rate_and_samples(schema):
    _run("upgrade", STORAGE, schema=schema)
    with _engine(schema).begin() as conn:
        rates_before = conn.execute(text("SELECT count(*) FROM usage_rate")).scalar_one()
        subject_id = conn.execute(
            text(
                "INSERT INTO usage_subject (kind, ref, first_seen_at, last_seen_at) "
                "VALUES ('bucket', 'dep-x', now(), now()) RETURNING id"
            )
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO usage_sample "
                "(subject_id, metric_id, window_start, interval_seconds, observed_at, value) "
                "SELECT :s, id, '2026-10-07 13:00', 3600, now(), 1 FROM usage_metric "
                "WHERE name = 'object_storage_byte_hours'"
            ),
            {"s": subject_id},
        )

    _run("downgrade", INDEX, schema=schema)
    with _engine(schema).begin() as conn:
        assert _metrics(conn) == {}
        assert conn.execute(text("SELECT count(*) FROM usage_sample")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM usage_rate")).scalar_one() == rates_before - 1


def test_the_fixture_catalog_matches_the_migration(schema):
    """`usage_fixtures` seeds a second copy; a metric added to one alone fails here."""
    from tests.usage_fixtures import OBJECT_STORAGE_CATALOG

    _run("upgrade", STORAGE, schema=schema)
    with _engine(schema).begin() as conn:
        assert _metrics(conn) == {name: tuple(rest) for name, *rest in OBJECT_STORAGE_CATALOG}
