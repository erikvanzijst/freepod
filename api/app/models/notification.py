"""The notification outbox: messages platform services queue for people, which
`daemons/notifier/` renders and delivers (notification-outbox,
notification-sender).

Producers only insert, through column grants that leave out `origin` and the
delivery columns; the notifier's role alone moves a row to a terminal state.
The wake-up trigger lives in the migration.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    Text,
    Uuid,
    text,
)
from sqlmodel import Field, SQLModel

from app.models.core import _utcnow


class NotificationState(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SUPPRESSED = "suppressed"


class NotificationKindORM(SQLModel, table=True):
    """A kind of notification that may be queued, seeded by migrations."""

    __tablename__ = "notification_kind"

    kind: str = Field(sa_column=Column(Text(), primary_key=True))
    unsubscribable: bool = Field(sa_column=Column(Boolean(), nullable=False))


class NotificationORM(SQLModel, table=True):
    """One message for one recipient, and how its delivery ended."""

    __tablename__ = "notification_outbox"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(recipient_user_id, recipient_email) = 1",
            name="ck_notification_outbox_one_recipient",
        ),
        CheckConstraint(
            "(action_label IS NULL) = (action_url IS NULL)",
            name="ck_notification_outbox_action_whole",
        ),
        CheckConstraint(
            "action_url IS NULL OR action_url LIKE 'https://%'",
            name="ck_notification_outbox_action_https",
        ),
        # One message per event and recipient. NULLS NOT DISTINCT because one
        # recipient column is always NULL; partial so keyless rows never conflict.
        Index(
            "uq_notification_outbox_dedupe",
            "kind",
            "dedupe_key",
            "recipient_user_id",
            "recipient_email",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where=text("dedupe_key IS NOT NULL"),
        ),
        Index(
            "ix_notification_outbox_pending",
            "created_at",
            postgresql_where=text("state = 'pending'"),
        ),
    )

    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(Uuid, primary_key=True, server_default=text("gen_random_uuid()")),
    )
    kind: str = Field(
        sa_column=Column(Text(), ForeignKey("notification_kind.kind"), nullable=False)
    )
    origin: str | None = Field(
        default=None,
        sa_column=Column(Text(), nullable=False, server_default=text("session_user")),
    )
    recipient_user_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=True),
    )
    recipient_email: str | None = Field(default=None, sa_column=Column(Text(), nullable=True))
    subject: str = Field(sa_column=Column(Text(), nullable=False))
    heading: str | None = Field(default=None, sa_column=Column(Text(), nullable=True))
    body: str = Field(sa_column=Column(Text(), nullable=False))
    action_label: str | None = Field(default=None, sa_column=Column(Text(), nullable=True))
    action_url: str | None = Field(default=None, sa_column=Column(Text(), nullable=True))
    reason: str = Field(sa_column=Column(Text(), nullable=False))
    dedupe_key: str | None = Field(default=None, sa_column=Column(Text(), nullable=True))
    state: NotificationState = Field(
        default=NotificationState.PENDING,
        sa_column=Column(
            SAEnum(
                NotificationState,
                name="notification_state",
                values_callable=lambda e: [m.value for m in e],
            ),
            nullable=False,
            server_default=text("'pending'"),
        ),
    )
    attempts: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default=text("0"))
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(
            DateTime(), nullable=False, server_default=text("(now() at time zone 'utc')")
        ),
    )
    last_attempt_at: datetime | None = Field(default=None, sa_column=Column(DateTime(), nullable=True))
    sent_at: datetime | None = Field(default=None, sa_column=Column(DateTime(), nullable=True))
    error: str | None = Field(default=None, sa_column=Column(Text(), nullable=True))
