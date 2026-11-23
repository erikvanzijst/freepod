from __future__ import annotations

import logging
from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator, Generator

from sqlmodel import Session, create_engine
from sqlalchemy.engine import Engine

from app.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """The process-wide engine, built on first use.

    Lazy rather than module-level so that changing ``CAELUS_DATABASE_URL``
    before the first database call is enough to retarget the process. The test
    suite relies on that; the alternative was reloading this module, which left
    an undisposed connection pool behind every time.
    """
    return create_engine(get_settings().database_url, echo=False, pool_pre_ping=True)


def get_session() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session


@contextmanager
def session_scope() -> Iterator[Session]:
    with Session(get_engine()) as session:
        try:
            yield session
        except Exception:
            logger.exception("Session scope failed; rolling back")
            session.rollback()
            raise
