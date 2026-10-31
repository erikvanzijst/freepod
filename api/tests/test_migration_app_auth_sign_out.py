"""Migration coverage for the sign-in and ended-session tables.

Follows ``test_migration_app_access``: a throwaway schema upgraded, exercised,
then downgraded again.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from tests.conftest import TEST_DATABASE_URL
from tests.test_migration_build_deployment import _deployment, _user
from tests.test_migration_namespace_unique import _upgrade

BEFORE = "b4d8f2a6c1e9"
SIGN_OUT = "c7e2a9d4f1b3"


@pytest.fixture
def migrated_schema():
    schema = f"mig_signout_{uuid4().hex[:8]}"
    admin = create_engine(TEST_DATABASE_URL)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        _upgrade("upgrade", SIGN_OUT, schema=schema)
        yield schema, create_engine(
            TEST_DATABASE_URL, connect_args={"options": f"-csearch_path={schema}"}
        )
    finally:
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


def _sign_in(conn, keycloak_sid: str, deployment_id) -> None:
    conn.execute(
        text(
            "INSERT INTO app_auth_sign_in (keycloak_sid, deployment_id, subject, sid, signed_in_at) "
            "VALUES (:k, :d, 's-1', 'app-sid', now())"
        ),
        {"k": keycloak_sid, "d": deployment_id},
    )


def test_one_sign_in_per_session_and_deployment(migrated_schema):
    _, engine = migrated_schema
    with engine.begin() as conn:
        deployment = _deployment(conn, _user(conn))
        _sign_in(conn, "kc-1", deployment)
        _sign_in(conn, "kc-2", deployment)
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            _sign_in(conn, "kc-1", deployment)


def test_sign_ins_go_with_their_deployment(migrated_schema):
    _, engine = migrated_schema
    with engine.begin() as conn:
        deployment = _deployment(conn, _user(conn))
        _sign_in(conn, "kc-1", deployment)
        conn.execute(text("DELETE FROM deployment_release WHERE deployment_id = :d"), {"d": deployment})
        conn.execute(text("DELETE FROM deployment WHERE id = :d"), {"d": deployment})
        assert conn.execute(text("SELECT count(*) FROM app_auth_sign_in")).scalar_one() == 0


def test_one_ended_session_per_id(migrated_schema):
    _, engine = migrated_schema
    insert = text("INSERT INTO app_auth_ended_session (keycloak_sid, ended_at) VALUES ('kc-1', now())")
    with engine.begin() as conn:
        conn.execute(insert)
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(insert)


def test_round_trips(migrated_schema):
    schema, _ = migrated_schema
    _upgrade("downgrade", BEFORE, schema=schema)
    _upgrade("upgrade", SIGN_OUT, schema=schema)
