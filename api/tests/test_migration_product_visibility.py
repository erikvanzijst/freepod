"""Migration coverage for `product.visibility`.

Each run migrates a throwaway schema (via
``PGOPTIONS=-csearch_path=...``) so it never touches the tables the rest of the
suite or a local dev database relies on.

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
from tests.conftest import TEST_DATABASE_URL


API_ROOT = Path(__file__).resolve().parents[1]
BEFORE_VISIBILITY = "a7b8c9d0e1f2"
VISIBILITY = "b1c2d3e4f5a6"
BEFORE_UNLISTED = "9e3b5a7c2d14"
UNLISTED = "c2e3d9b293fb"


def _alembic(*args: str, schema: str) -> None:
    result = subprocess.run(
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
    assert result.returncode == 0, f"alembic {' '.join(args)} failed:\n{result.stderr}"


@pytest.fixture
def migrated_schema():
    """A throwaway schema migrated to the revision *before* visibility."""
    schema = f"mig_visibility_{uuid4().hex[:8]}"
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        _alembic("upgrade", BEFORE_VISIBILITY, schema=schema)
        yield schema, create_engine(
            TEST_DATABASE_URL, connect_args={"options": f"-csearch_path={schema}"}
        )
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


def test_migration_backfills_existing_products_to_public(migrated_schema):
    """Existing products keep today's behavior: offered to every end user."""
    schema, engine = migrated_schema
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO product (name, created_at) VALUES ('legacy', now())")
        )

    _alembic("upgrade", VISIBILITY, schema=schema)

    with engine.begin() as conn:
        rows = conn.execute(text("SELECT name, visibility FROM product")).all()
    assert rows == [("legacy", "public")]


def test_rows_created_after_the_migration_default_to_admin(migrated_schema):
    """The column's server default keeps new products hidden."""
    schema, engine = migrated_schema
    _alembic("upgrade", VISIBILITY, schema=schema)

    with engine.begin() as conn:
        conn.execute(text("INSERT INTO product (name, created_at) VALUES ('fresh', now())"))
        visibility = conn.execute(
            text("SELECT visibility FROM product WHERE name = 'fresh'")
        ).scalar_one()
    assert visibility == "admin"


def test_visibility_is_not_nullable(migrated_schema):
    schema, engine = migrated_schema
    _alembic("upgrade", VISIBILITY, schema=schema)

    with engine.begin() as conn:
        nullable = conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = 'product' "
                "AND column_name = 'visibility'"
            ),
            {"schema": schema},
        ).scalar_one()
    assert nullable == "NO"


def test_downgrade_removes_the_column(migrated_schema):
    schema, engine = migrated_schema
    _alembic("upgrade", VISIBILITY, schema=schema)
    _alembic("downgrade", BEFORE_VISIBILITY, schema=schema)

    with engine.begin() as conn:
        columns = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = 'product'"
            ),
            {"schema": schema},
        ).scalars().all()
    assert "visibility" not in columns


# ---------------------------------------------------------------------------
# The `unlisted` value
# ---------------------------------------------------------------------------


def _enum_labels(engine, schema: str) -> list[str]:
    with engine.begin() as conn:
        return conn.execute(
            text(
                "SELECT e.enumlabel FROM pg_enum e "
                "JOIN pg_type t ON t.oid = e.enumtypid "
                "JOIN pg_namespace n ON n.oid = t.typnamespace "
                "WHERE t.typname = 'productvisibility' AND n.nspname = :schema "
                "ORDER BY e.enumsortorder"
            ),
            {"schema": schema},
        ).scalars().all()


def _visibilities(engine) -> list[tuple[str, str]]:
    with engine.begin() as conn:
        return conn.execute(
            text("SELECT name, visibility::text FROM product ORDER BY name")
        ).all()


@pytest.fixture
def before_unlisted(migrated_schema):
    """A throwaway schema at the revision before `unlisted`, with one product per value."""
    schema, engine = migrated_schema
    _alembic("upgrade", BEFORE_UNLISTED, schema=schema)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO product (name, created_at, visibility) VALUES "
                "('listed', now(), 'public'), ('hidden', now(), 'admin')"
            )
        )
    return schema, engine


def test_unlisted_upgrade_changes_no_existing_product(before_unlisted):
    schema, engine = before_unlisted

    _alembic("upgrade", UNLISTED, schema=schema)

    assert _enum_labels(engine, schema) == ["public", "admin", "unlisted"]
    assert _visibilities(engine) == [("hidden", "admin"), ("listed", "public")]


def test_unlisted_is_accepted_and_the_default_stays_admin(before_unlisted):
    schema, engine = before_unlisted
    _alembic("upgrade", UNLISTED, schema=schema)

    with engine.begin() as conn:
        conn.execute(text("UPDATE product SET visibility = 'unlisted' WHERE name = 'listed'"))
        conn.execute(text("INSERT INTO product (name, created_at) VALUES ('fresh', now())"))

    assert _visibilities(engine) == [
        ("fresh", "admin"),
        ("hidden", "admin"),
        ("listed", "unlisted"),
    ]


def test_unlisted_upgrade_is_idempotent_against_an_existing_value(before_unlisted):
    """`IF NOT EXISTS`: a value already present is not an error."""
    schema, engine = before_unlisted
    with engine.begin() as conn:
        conn.execute(text("ALTER TYPE productvisibility ADD VALUE 'unlisted'"))

    _alembic("upgrade", UNLISTED, schema=schema)

    assert _enum_labels(engine, schema) == ["public", "admin", "unlisted"]


def test_unlisted_downgrade_makes_unlisted_products_public(before_unlisted):
    schema, engine = before_unlisted
    _alembic("upgrade", UNLISTED, schema=schema)
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO product (name, created_at, visibility) VALUES ('dev', now(), 'unlisted')")
        )

    _alembic("downgrade", BEFORE_UNLISTED, schema=schema)

    assert _enum_labels(engine, schema) == ["public", "admin"]
    assert _visibilities(engine) == [("dev", "public"), ("hidden", "admin"), ("listed", "public")]
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO product (name, created_at) VALUES ('fresh', now())"))
        default = conn.execute(
            text("SELECT visibility::text FROM product WHERE name = 'fresh'")
        ).scalar_one()
    assert default == "admin"

    _alembic("upgrade", UNLISTED, schema=schema)
    assert _enum_labels(engine, schema) == ["public", "admin", "unlisted"]
