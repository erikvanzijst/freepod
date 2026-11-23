from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
from sqlmodel import Session

from app.config import get_settings
from app.db import get_engine


def _backend_pid() -> int:
    with Session(get_engine()) as session:
        return session.exec(text("select pg_backend_pid()")).scalar_one()


def test_pooled_connection_killed_by_the_server_is_replaced():
    get_engine().dispose()
    stale = _backend_pid()

    admin = create_engine(get_settings().database_url, poolclass=NullPool)
    with admin.connect() as conn:
        assert conn.execute(text("select pg_terminate_backend(:pid, 5000)"), {"pid": stale}).scalar_one()
    admin.dispose()

    assert _backend_pid() != stale
