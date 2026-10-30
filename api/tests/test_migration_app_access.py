"""Migration coverage for the access list and invitation tables.

Follows ``test_migration_app_auth``: a throwaway schema upgraded, exercised,
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

BEFORE = "a3c9e1f7b2d4"
APP_ACCESS = "b4d8f2a6c1e9"


@pytest.fixture
def migrated_schema():
    schema = f"mig_appaccess_{uuid4().hex[:8]}"
    admin = create_engine(TEST_DATABASE_URL)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        _upgrade("upgrade", APP_ACCESS, schema=schema)
        yield schema, create_engine(
            TEST_DATABASE_URL, connect_args={"options": f"-csearch_path={schema}"}
        )
    finally:
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


def _entry(conn, deployment_id, email: str, subject: str | None = None) -> None:
    conn.execute(
        text(
            "INSERT INTO app_access_entry (id, deployment_id, email, subject, created_at) "
            "VALUES (:i, :d, :e, :s, now())"
        ),
        {"i": uuid4(), "d": deployment_id, "e": email, "s": subject},
    )


def test_one_entry_per_email(migrated_schema):
    _, engine = migrated_schema
    with engine.begin() as conn:
        deployment = _deployment(conn, _user(conn))
        _entry(conn, deployment, "ana@example.com")
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            _entry(conn, deployment, "ana@example.com")


def test_one_entry_per_subject(migrated_schema):
    _, engine = migrated_schema
    with engine.begin() as conn:
        deployment = _deployment(conn, _user(conn))
        _entry(conn, deployment, "ana@example.com", subject="s-1")
        _entry(conn, deployment, "jules@example.org")
        _entry(conn, deployment, "noor@example.org")
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE app_access_entry SET subject = 's-1' WHERE email = 'jules@example.org'")
            )


def test_email_is_lower_case(migrated_schema):
    _, engine = migrated_schema
    with engine.begin() as conn:
        deployment = _deployment(conn, _user(conn))
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            _entry(conn, deployment, "Ana@example.com")


def test_entries_go_with_their_deployment(migrated_schema):
    _, engine = migrated_schema
    with engine.begin() as conn:
        deployment = _deployment(conn, _user(conn))
        _entry(conn, deployment, "ana@example.com")
        conn.execute(text("DELETE FROM deployment_release WHERE deployment_id = :d"), {"d": deployment})
        conn.execute(text("DELETE FROM deployment WHERE id = :d"), {"d": deployment})
        assert conn.execute(text("SELECT count(*) FROM app_access_entry")).scalar_one() == 0


def test_invitations_go_with_their_owner(migrated_schema):
    _, engine = migrated_schema
    with engine.begin() as conn:
        owner = _user(conn)
        conn.execute(
            text("INSERT INTO app_access_invitation (id, user_id, sent_at) VALUES (:i, :u, now())"),
            {"i": uuid4(), "u": owner},
        )
        conn.execute(text('DELETE FROM "user" WHERE id = :u'), {"u": owner})
        assert conn.execute(text("SELECT count(*) FROM app_access_invitation")).scalar_one() == 0


def test_round_trips(migrated_schema):
    schema, _ = migrated_schema
    _upgrade("downgrade", BEFORE, schema=schema)
    _upgrade("upgrade", APP_ACCESS, schema=schema)
