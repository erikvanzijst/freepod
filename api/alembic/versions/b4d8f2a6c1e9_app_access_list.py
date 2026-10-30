"""app access list

Adds ``app_access_entry``, the people the owner of a ``listed`` deployment
admits, and ``app_access_invitation``, the invitations owners have sent,
counted against a daily limit.

Revision ID: b4d8f2a6c1e9
Revises: a3c9e1f7b2d4
Create Date: 2026-10-29

"""
from alembic import op
import sqlalchemy as sa


revision = "b4d8f2a6c1e9"
down_revision = "a3c9e1f7b2d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_access_entry",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("deployment_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("bound_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("email = lower(email)", name="ck_app_access_entry_email_lower"),
        sa.ForeignKeyConstraint(["deployment_id"], ["deployment.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("deployment_id", "email", name="uq_app_access_entry_email"),
    )
    op.create_index(
        "uq_app_access_entry_subject",
        "app_access_entry",
        ["deployment_id", "subject"],
        unique=True,
        postgresql_where=sa.text("subject IS NOT NULL"),
    )
    op.create_table(
        "app_access_invitation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_app_access_invitation_user_sent", "app_access_invitation", ["user_id", "sent_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_app_access_invitation_user_sent", table_name="app_access_invitation")
    op.drop_table("app_access_invitation")
    op.drop_index("uq_app_access_entry_subject", table_name="app_access_entry")
    op.drop_table("app_access_entry")
