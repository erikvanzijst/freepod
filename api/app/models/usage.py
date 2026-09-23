"""The usage ledger: ``usage_metric`` catalogs what the platform measures,
``usage_subject`` names what it measures against, ``usage_sample`` holds the values.

The catalog is a table rather than an enum so that an unconstrained metric name cannot
silently create a new series. Nothing here stores money.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Optional
from uuid import UUID

from sqlmodel import Field, SQLModel
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)


def _utcnow() -> datetime:
    """Naive UTC, matching the schema's timestamp columns."""
    return datetime.now(UTC).replace(tzinfo=None)


class MetricAxis(StrEnum):
    CPU = "cpu"
    MEMORY = "memory"
    NETWORK = "network"
    STORAGE = "storage"
    RUNTIME = "runtime"


class MetricUnit(StrEnum):
    CORE_HOURS = "core_hours"
    CORES = "cores"
    BYTE_HOURS = "byte_hours"
    BYTES = "bytes"
    SECONDS = "seconds"


class MetricKind(StrEnum):
    """How a value aggregates: ``DELTA`` accrued within the window, ``GAUGE`` was held
    across it and is scaled by the window length by the ``usage_amount`` view."""

    DELTA = "delta"
    GAUGE = "gauge"


class MetricRole(StrEnum):
    """Consumption, or an allowance such as a request, limit or quota."""

    USAGE = "usage"
    ALLOCATION = "allocation"


class SubjectKind(StrEnum):
    CONTAINER = "container"
    PV = "pv"
    BUCKET = "bucket"
    DATABASE = "database"
    NODE = "node"


class UsageMetricORM(SQLModel, table=True):
    """One catalogued quantity. Adding an axis is an insert, not a migration."""

    __tablename__ = "usage_metric"

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            SmallInteger(),
            Identity(always=True),
            primary_key=True,
            autoincrement=True,
        ),
    )
    name: str = Field(sa_column=Column(Text(), nullable=False, unique=True))
    axis: MetricAxis = Field(sa_column=Column(Text(), nullable=False))
    unit: MetricUnit = Field(sa_column=Column(Text(), nullable=False))
    kind: MetricKind = Field(sa_column=Column(Text(), nullable=False))
    role: MetricRole = Field(sa_column=Column(Text(), nullable=False))


class UsageSubjectORM(SQLModel, table=True):
    """What is being measured.

    ``ref`` is stable for the subject's lifetime; a re-created volume or bucket is a
    new subject. ``deployment_id`` is NULL for a platform namespace and may be filled
    in later, which never touches samples.
    """

    __tablename__ = "usage_subject"
    __table_args__ = (
        UniqueConstraint("kind", "ref", name="uq_usage_subject_kind_ref"),
        # Partial: platform subjects are never on the billing join.
        Index(
            "ix_usage_subject_deployment",
            "deployment_id",
            postgresql_where=Column("deployment_id").isnot(None),
        ),
        Index("ix_usage_subject_namespace", "namespace"),
    )

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer(),
            Identity(always=True),
            primary_key=True,
            autoincrement=True,
        ),
    )
    kind: SubjectKind = Field(sa_column=Column(Text(), nullable=False))
    ref: str = Field(sa_column=Column(Text(), nullable=False))
    namespace: Optional[str] = Field(
        default=None, sa_column=Column(String(), nullable=True)
    )
    # No cascade: attribution must survive the deployment's deletion.
    deployment_id: Optional[UUID] = Field(
        default=None,
        sa_column=Column(Uuid, ForeignKey("deployment.id"), nullable=True),
    )
    first_seen_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(), nullable=False),
    )
    last_seen_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(), nullable=False),
    )


class UsageSampleORM(SQLModel, table=True):
    """One measured value, for one subject and quantity, over one window.

    The primary key is natural: it is the identity the spec gives a sample, covers the
    two hottest read paths, and keeps the TimescaleDB exit open. ``interval_seconds``
    and ``observed_at`` are on the row so a sample survives a cadence change.
    """

    __tablename__ = "usage_sample"
    __table_args__ = (
        PrimaryKeyConstraint("subject_id", "metric_id", "window_start"),
        # btree rather than BRIN: BRIN cannot answer the resume position's max()
        # without scanning the table.
        Index("ix_usage_sample_window", "window_start"),
    )

    subject_id: int = Field(
        sa_column=Column(Integer, ForeignKey("usage_subject.id"), nullable=False)
    )
    metric_id: int = Field(
        sa_column=Column(SmallInteger, ForeignKey("usage_metric.id"), nullable=False)
    )
    window_start: datetime = Field(sa_column=Column(DateTime(), nullable=False))
    interval_seconds: int = Field(sa_column=Column(Integer(), nullable=False))
    observed_at: datetime = Field(sa_column=Column(DateTime(), nullable=False))
    value: Decimal = Field(sa_column=Column(Numeric(), nullable=False))
