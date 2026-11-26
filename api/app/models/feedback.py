"""Feedback people send from the dashboard and public pages, and the screenshot
each may carry (feedback-data-model). The screenshot lives in its own table so
listing submissions never reads image bytes (add-feedback D5, D6)."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Optional

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.core import _utcnow


class FeedbackTopic(StrEnum):
    BUG = "bug"
    IDEA = "idea"
    OTHER = "other"


FEEDBACK_TOPIC_LABELS = {
    FeedbackTopic.BUG: "Something is wrong",
    FeedbackTopic.IDEA: "An idea",
    FeedbackTopic.OTHER: "Something else",
}

FEEDBACK_MESSAGE_MAX = 5000


class FeedbackORM(SQLModel, table=True):
    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint(
            f"message ~ '[^[:space:]]' AND char_length(message) <= {FEEDBACK_MESSAGE_MAX}",
            name="ck_feedback_message_length",
        ),
        Index("ix_feedback_created_at", "created_at"),
        Index(
            "ix_feedback_open_created_at",
            "created_at",
            postgresql_where=text("resolved_at IS NULL"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=_utcnow, sa_column=Column(DateTime(), nullable=False))
    user_id: int = Field(
        sa_column=Column(Integer, ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, index=True)
    )
    email: str = Field(sa_column=Column(Text(), nullable=False))
    topic: FeedbackTopic = Field(
        sa_column=Column(
            SAEnum(FeedbackTopic, name="feedback_topic", values_callable=lambda e: [m.value for m in e]),
            nullable=False,
        )
    )
    message: str = Field(sa_column=Column(Text(), nullable=False))
    page: str = Field(sa_column=Column(Text(), nullable=False))
    user_agent: str | None = Field(default=None, sa_column=Column(Text(), nullable=True))
    viewport: str | None = Field(default=None, sa_column=Column(Text(), nullable=True))
    ui_build: str | None = Field(default=None, sa_column=Column(Text(), nullable=True))
    api_build: str | None = Field(default=None, sa_column=Column(Text(), nullable=True))
    diagnostics: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSONB(), nullable=False, server_default=text("'[]'::jsonb")),
    )
    read_at: datetime | None = Field(default=None, sa_column=Column(DateTime(), nullable=True))
    resolved_at: datetime | None = Field(default=None, sa_column=Column(DateTime(), nullable=True))
    resolved_by: int | None = Field(
        default=None, sa_column=Column(Integer, ForeignKey("user.id", ondelete="RESTRICT"), nullable=True)
    )


class FeedbackScreenshotORM(SQLModel, table=True):
    __tablename__ = "feedback_screenshot"

    feedback_id: int = Field(
        sa_column=Column(Integer, ForeignKey("feedback.id", ondelete="CASCADE"), primary_key=True)
    )
    media_type: str = Field(sa_column=Column(Text(), nullable=False))
    width: int = Field(sa_column=Column(Integer, nullable=False))
    height: int = Field(sa_column=Column(Integer, nullable=False))
    data: bytes = Field(sa_column=Column(LargeBinary(), nullable=False))


class FeedbackSummary(SQLModel):
    id: int
    created_at: datetime
    user_id: int
    email: str
    topic: FeedbackTopic
    excerpt: str
    page: str
    has_screenshot: bool
    read: bool
    resolved: bool


class FeedbackListRead(SQLModel):
    items: list[FeedbackSummary]
    total: int
    unread: int


class FeedbackRead(SQLModel):
    id: int
    created_at: datetime
    user_id: int
    email: str
    topic: FeedbackTopic
    message: str
    page: str
    user_agent: str | None
    viewport: str | None
    ui_build: str | None
    api_build: str | None
    diagnostics: list[dict[str, Any]]
    has_screenshot: bool
    screenshot_width: int | None = None
    screenshot_height: int | None = None
    read_at: datetime | None
    resolved_at: datetime | None
    resolved_by: int | None
    resolved_by_email: str | None = None


class FeedbackCreated(SQLModel):
    id: int


class FeedbackUpdate(SQLModel):
    resolved: bool
