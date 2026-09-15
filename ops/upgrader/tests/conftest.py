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


def _test_database_url() -> str:
    url = os.environ.get("UPGRADER_TEST_DATABASE_URL")
    if url:
        return url
    base = os.environ.get("CAELUS_TEST_DATABASE_URL")
    if not base:
        raise pytest.UsageError(
            "Set UPGRADER_TEST_DATABASE_URL to a Postgres database the suite may drop and "
            "recreate (the connecting user needs CREATEDB)."
        )
    return make_url(base).set(database="upgrader_test").render_as_string(hide_password=False)


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
