"""feedback

The ``feedback`` and ``feedback_screenshot`` tables, the ``feedback_topic``
enum, and the notification kind ``feedback.submitted``.

Revision ID: c4f1e8a2b9d7
Revises: f5ae9632f172
Create Date: 2026-11-26

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "c4f1e8a2b9d7"
down_revision = "f5ae9632f172"
branch_labels = None
depends_on = None


def upgrade() -> None:
    topic = postgresql.ENUM("bug", "idea", "other", name="feedback_topic", create_type=False)
    topic.create(op.get_bind())
    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("topic", topic, nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("page", sa.Text(), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("viewport", sa.Text(), nullable=True),
        sa.Column("ui_build", sa.Text(), nullable=True),
        sa.Column("api_build", sa.Text(), nullable=True),
        sa.Column(
            "diagnostics", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="RESTRICT"), nullable=True),
        sa.CheckConstraint(
            "message ~ '[^[:space:]]' AND char_length(message) <= 5000", name="ck_feedback_message_length"
        ),
    )
    op.create_index("ix_feedback_user_id", "feedback", ["user_id"])
    op.create_index("ix_feedback_created_at", "feedback", ["created_at"])
    op.create_index(
        "ix_feedback_open_created_at",
        "feedback",
        ["created_at"],
        postgresql_where=sa.text("resolved_at IS NULL"),
    )
    op.create_table(
        "feedback_screenshot",
        sa.Column(
            "feedback_id",
            sa.Integer(),
            sa.ForeignKey("feedback.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
    )
    op.execute("INSERT INTO notification_kind (kind, unsubscribable) VALUES ('feedback.submitted', false)")


def downgrade() -> None:
    op.execute("DELETE FROM notification_outbox WHERE kind = 'feedback.submitted'")
    op.execute("DELETE FROM notification_kind WHERE kind = 'feedback.submitted'")
    op.drop_table("feedback_screenshot")
    op.drop_table("feedback")
    postgresql.ENUM(name="feedback_topic").drop(op.get_bind())
