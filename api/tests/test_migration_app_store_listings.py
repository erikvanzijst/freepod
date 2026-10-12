"""Migration coverage for the store-listing columns, template versions and
product releases.

Each run migrates a throwaway schema (via ``PGOPTIONS=-csearch_path=...``), and
Alembic runs as a subprocess, for the reasons given in
``test_migration_product_visibility.py``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from tests.conftest import TEST_DATABASE_URL


API_ROOT = Path(__file__).resolve().parents[1]
BEFORE = "c2e3d9b293fb"
LISTINGS = "d4f1a8c3e2b7"


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
def seeded_schema():
    """A schema at the revision before listings, holding a product and a template."""
    schema = f"mig_listings_{uuid4().hex[:8]}"
    admin = create_engine(TEST_DATABASE_URL)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(TEST_DATABASE_URL, connect_args={"options": f"-csearch_path={schema}"})
    try:
        _alembic("upgrade", BEFORE, schema=schema)
        with engine.begin() as conn:
            product_id = conn.execute(
                text(
                    "INSERT INTO product (name, description, created_at) "
                    "VALUES ('Immich', 'Photos', now()) RETURNING id"
                )
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO product_template_version "
                    "(product_id, chart_ref, chart_version, created_at) "
                    "VALUES (:p, 'oci://example/immich', '1.0.0', now())"
                ),
                {"p": product_id},
            )
        yield schema, engine
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_upgrade_keeps_existing_rows_with_empty_listing(seeded_schema):
    schema, engine = seeded_schema
    _alembic("upgrade", LISTINGS, schema=schema)

    with engine.connect() as conn:
        product = conn.execute(
            text("SELECT name, description, tagline, license, features, links, screenshots FROM product")
        ).one()
        versions = conn.execute(text("SELECT version FROM product_template_version")).scalars().all()
        releases = conn.execute(text("SELECT count(*) FROM product_release")).scalar_one()

    assert product.name == "Immich" and product.description == "Photos"
    assert product.tagline is None and product.license is None
    assert (product.features, product.links, product.screenshots) == ([], [], [])
    assert versions == [None]
    assert releases == 0


def test_release_versions_are_unique_per_product(seeded_schema):
    schema, engine = seeded_schema
    _alembic("upgrade", LISTINGS, schema=schema)

    insert = text(
        "INSERT INTO product_release (product_id, version, notes, position, created_at, updated_at) "
        "SELECT id, '3.3.1', 'Notes', 0, now(), now() FROM product"
    )
    with engine.begin() as conn:
        conn.execute(insert)
    with pytest.raises(Exception, match="uq_product_release_product_version"):
        with engine.begin() as conn:
            conn.execute(insert)


def test_downgrade_removes_listing_schema(seeded_schema):
    schema, engine = seeded_schema
    _alembic("upgrade", LISTINGS, schema=schema)
    _alembic("downgrade", BEFORE, schema=schema)

    inspector = inspect(engine)
    product_columns = {c["name"] for c in inspector.get_columns("product", schema=schema)}
    template_columns = {
        c["name"] for c in inspector.get_columns("product_template_version", schema=schema)
    }
    assert not {"tagline", "license", "features", "links", "screenshots"} & product_columns
    assert "version" not in template_columns
    assert "product_release" not in inspector.get_table_names(schema=schema)
