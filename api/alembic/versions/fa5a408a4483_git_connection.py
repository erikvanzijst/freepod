"""A user's connections to git hosting providers

Revision ID: fa5a408a4483
Revises: f1d7c3a9e5b2
Create Date: 2026-11-17

"""
from alembic import op
import sqlalchemy as sa


revision = "fa5a408a4483"
down_revision = "f1d7c3a9e5b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "git_connection",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("host", sa.String(253), nullable=False),
        sa.Column("account_id", sa.String(64), nullable=False),
        sa.Column("login", sa.String(255), nullable=False),
        sa.Column("tokens_encrypted", sa.Text(), nullable=False),
        sa.Column("key_id", sa.String(8), nullable=False),
        sa.Column("access_token_expires_at", sa.DateTime(), nullable=True),
        sa.Column("refresh_token_expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "uq_git_connection_user", "git_connection", ["user_id", "provider", "host"], unique=True
    )
    op.create_index(
        "uq_git_connection_account",
        "git_connection",
        ["provider", "host", "account_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("git_connection")
