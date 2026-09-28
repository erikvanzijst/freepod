"""Migration coverage for app authentication's consent and code tables.

Follows ``test_migration_build_usage``: a throwaway schema at the revision before,
upgraded, exercised, then downgraded again.
"""

from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from tests.conftest import TEST_DATABASE_URL
from tests.test_migration_build_deployment import _deployment, _user
from tests.test_migration_namespace_unique import _upgrade

BEFORE = "9df604f2b702"
APP_AUTH = "d71152c7e6ff"


@pytest.fixture
def migrated_schema():
    schema = f"mig_appauth_{uuid4().hex[:8]}"
    admin = create_engine(TEST_DATABASE_URL)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        _upgrade("upgrade", APP_AUTH, schema=schema)
        yield schema, create_engine(
            TEST_DATABASE_URL, connect_args={"options": f"-csearch_path={schema}"}
        )
    finally:
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


def _consent(conn, subject: str, deployment_id) -> None:
    conn.execute(
        text(
            "INSERT INTO app_auth_consent (subject, deployment_id, claims, granted_at) "
            "VALUES (:s, :d, ARRAY['sub','email','name'], now())"
        ),
        {"s": subject, "d": deployment_id},
    )


def test_one_consent_per_subject_and_deployment(migrated_schema):
    _, engine = migrated_schema
    with engine.begin() as conn:
        deployment = _deployment(conn, _user(conn))
        _consent(conn, "3f2a", deployment)
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            _consent(conn, "3f2a", deployment)


def test_code_hash_must_be_a_sha256(migrated_schema):
    _, engine = migrated_schema
    insert = text(
        "INSERT INTO app_auth_code "
        "(code_hash, host, subject, email, name, return_path, nonce_hash, expires_at) "
        "VALUES (:c, 'milk.example', 's', 'e@x', '', '/', :n, now())"
    )
    digest = hashlib.sha256(b"x").digest()
    with engine.begin() as conn:
        conn.execute(insert, {"c": digest, "n": digest})
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(insert, {"c": b"raw-code", "n": digest})


def test_round_trips(migrated_schema):
    schema, _ = migrated_schema
    _upgrade("downgrade", BEFORE, schema=schema)
    _upgrade("upgrade", APP_AUTH, schema=schema)
