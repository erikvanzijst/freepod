"""Shared fixtures. Database tests run against a real Postgres, created empty and migrated
with the real Alembic chain once per session (D15)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, delete, text
from sqlalchemy.engine import make_url

from upgrader import db

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]
_NO_URL = """\
UPGRADER_TEST_DATABASE_URL is not set.

This test suite requires a reachable PostgreSQL server; it has no
in-memory mode. Inside the devcontainer the variable is set for you by
docker-compose.yml. Outside it:

    docker compose up -d postgres
    export UPGRADER_TEST_DATABASE_URL=postgresql+psycopg://caelus:caelus@postgres:5432/upgrader_test

The connecting user must hold CREATEDB (or be a superuser): the suite
creates and migrates the test database itself.
"""


def _test_database_url() -> str:
    raw = os.environ.get("UPGRADER_TEST_DATABASE_URL")
    if not raw:
        raise pytest.UsageError(_NO_URL)
    if not make_url(raw).database:
        raise pytest.UsageError(
            f"UPGRADER_TEST_DATABASE_URL names no database: {raw!r}"
        )
    return raw


@pytest.fixture(scope="session")
def database_url():
    url = make_url(_test_database_url())
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()
    rendered = url.render_as_string(hide_password=False)
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": rendered},
        check=True,
        capture_output=True,
    )
    return rendered


@pytest.fixture
def Session(database_url):
    engine = create_engine(database_url)
    maker = db.make_sessionmaker(engine)
    with maker.begin() as session:
        session.execute(delete(db.ProductResult))
        session.execute(delete(db.Run))
    yield maker
    engine.dispose()
