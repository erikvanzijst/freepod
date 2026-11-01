"""Migration coverage for ``user.keycloak_subject``.

Follows ``test_migration_app_auth_sign_out``: a throwaway schema upgraded,
exercised, then downgraded again.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from tests.conftest import TEST_DATABASE_URL
from tests.test_migration_build_deployment import _user
from tests.test_migration_namespace_unique import _upgrade

BEFORE = "c7e2a9d4f1b3"
SUBJECT = "f3a8d1c6b9e2"


@pytest.fixture
def migrated_schema():
    schema = f"mig_subject_{uuid4().hex[:8]}"
    admin = create_engine(TEST_DATABASE_URL)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        _upgrade("upgrade", SUBJECT, schema=schema)
        yield schema, create_engine(
            TEST_DATABASE_URL, connect_args={"options": f"-csearch_path={schema}"}
        )
    finally:
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


def _bind(conn, user_id: int, subject: str | None) -> None:
    conn.execute(
        text('UPDATE "user" SET keycloak_subject = :s WHERE id = :u'),
        {"s": subject, "u": user_id},
    )


def test_existing_records_start_unbound(migrated_schema):
    _, engine = migrated_schema
    with engine.begin() as conn:
        user = _user(conn)
        subject = conn.execute(
            text('SELECT keycloak_subject FROM "user" WHERE id = :u'), {"u": user}
        ).scalar_one()
    assert subject is None


def test_one_live_record_per_subject(migrated_schema):
    _, engine = migrated_schema
    with engine.begin() as conn:
        _bind(conn, _user(conn), "kc-1")
        other = _user(conn)
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            _bind(conn, other, "kc-1")


def test_unbound_records_do_not_collide(migrated_schema):
    _, engine = migrated_schema
    with engine.begin() as conn:
        _bind(conn, _user(conn), None)
        _bind(conn, _user(conn), None)


def test_a_deleted_record_releases_its_subject(migrated_schema):
    _, engine = migrated_schema
    with engine.begin() as conn:
        gone = _user(conn)
        _bind(conn, gone, "kc-1")
        conn.execute(text('UPDATE "user" SET deleted_at = now() WHERE id = :u'), {"u": gone})
        _bind(conn, _user(conn), "kc-1")


def test_subjects_compare_exactly(migrated_schema):
    _, engine = migrated_schema
    with engine.begin() as conn:
        _bind(conn, _user(conn), "AbC")
        _bind(conn, _user(conn), "abc")


def test_round_trips(migrated_schema):
    schema, _ = migrated_schema
    _upgrade("downgrade", BEFORE, schema=schema)
    _upgrade("upgrade", SUBJECT, schema=schema)
