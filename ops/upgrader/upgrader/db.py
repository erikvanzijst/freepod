"""The run history's index in Postgres (product-upgrade-history, D6)."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from sqlalchemy import ForeignKey, String, Text, create_engine, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

RUNNING = "running"


def now() -> datetime:
    return datetime.now(UTC)


def database_url(env=None) -> str:
    env = os.environ if env is None else env
    url = env["DATABASE_URL"]
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def make_sessionmaker(engine: Engine | None = None) -> sessionmaker:
    engine = engine or create_engine(database_url(), pool_pre_ping=True)
    return sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    trigger: Mapped[str] = mapped_column(String(16))
    scope: Mapped[str | None] = mapped_column(String(64))
    dry_run: Mapped[bool]
    state: Mapped[str] = mapped_column(String(16), default=RUNNING)
    started_at: Mapped[datetime] = mapped_column(default=now)
    finished_at: Mapped[datetime | None]
    pi_version: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(200))
    thinking_level: Mapped[str | None] = mapped_column(String(16))

    products: Mapped[list[ProductResult]] = relationship(
        back_populates="run", order_by="ProductResult.id", lazy="selectin"
    )


class ProductResult(Base):
    __tablename__ = "product_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    slug: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(16), default=RUNNING)
    current_version: Mapped[str | None] = mapped_column(String(200))
    target_version: Mapped[str | None] = mapped_column(String(200))
    pr_url: Mapped[str | None] = mapped_column(Text)
    draft: Mapped[bool | None]
    branch: Mapped[str | None] = mapped_column(Text)
    skip_reason: Mapped[str | None] = mapped_column(Text)
    needs_human: Mapped[list] = mapped_column(JSONB, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(default=now)
    finished_at: Mapped[datetime | None]
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    peak_context: Mapped[int | None]
    commit: Mapped[str | None] = mapped_column(String(64))
    files: Mapped[list] = mapped_column(JSONB, default=list)

    run: Mapped[Run] = relationship(back_populates="products")


def close_interrupted(Session: sessionmaker) -> None:
    """D5: whatever has no finish time was cut short by the restart that is now starting."""
    stamp = now()
    with Session.begin() as session:
        session.execute(
            update(ProductResult)
            .where(ProductResult.finished_at.is_(None))
            .values(outcome="interrupted", finished_at=stamp)
        )
        session.execute(
            update(Run).where(Run.finished_at.is_(None)).values(state="interrupted", finished_at=stamp)
        )
