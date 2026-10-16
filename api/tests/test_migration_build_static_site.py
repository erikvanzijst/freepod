"""Migration coverage for ``build.static_site``: existing builds read false.

Follows ``test_migration_build_usage``: a throwaway schema migrated to the
revision before this one, seeded by hand, then upgraded and inspected.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from tests.conftest import TEST_DATABASE_URL
from tests.test_migration_build_deployment import _deployment, _user
from tests.test_migration_build_usage import _build, _columns
from tests.test_migration_namespace_unique import _upgrade

BEFORE = "d4f1a8c3e2b7"
STATIC_SITE = "e2f3a4b5c6d7"


@pytest.fixture
def migrated_schema():
    schema = f"mig_staticsite_{uuid4().hex[:8]}"
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


def test_existing_builds_are_not_static_sites(migrated_schema):
    schema, engine = migrated_schema
    with engine.begin() as conn:
        deployment = _deployment(conn, _user(conn))
        for status in ("succeeded", "failed", "running"):
            _build(conn, deployment, status)

    _upgrade("upgrade", STATIC_SITE, schema=schema)

    with engine.begin() as conn:
        flags = conn.execute(text("SELECT static_site FROM build")).scalars().all()
    assert flags == [False, False, False]


def test_the_downgrade_round_trips(migrated_schema):
    schema, engine = migrated_schema
    _upgrade("upgrade", STATIC_SITE, schema=schema)
    with engine.begin() as conn:
        assert "static_site" in _columns(conn, schema)

    _upgrade("downgrade", BEFORE, schema=schema)
    with engine.begin() as conn:
        assert "static_site" not in _columns(conn, schema)

    _upgrade("upgrade", STATIC_SITE, schema=schema)
