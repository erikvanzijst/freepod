"""app auth

Adds the records app authentication keeps: ``app_auth_consent``, one row per
(Keycloak subject, deployment) that agreed to disclose its identity to that app,
and ``app_auth_code``, the broker's single-use sign-in codes, stored hashed.
Both are written only by ``app-auth/``.

Revision ID: d71152c7e6ff
Revises: 9df604f2b702
Create Date: 2026-09-27

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "d71152c7e6ff"
down_revision = "9df604f2b702"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_auth_consent",
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("deployment_id", sa.Uuid(), nullable=False),
        sa.Column("claims", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("granted_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["deployment_id"], ["deployment.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("subject", "deployment_id"),
    )
    op.create_table(
        "app_auth_code",
        sa.Column("code_hash", sa.LargeBinary(), nullable=False),
        sa.Column("host", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("return_path", sa.Text(), nullable=False),
        sa.Column("nonce_hash", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("octet_length(code_hash) = 32", name="ck_app_auth_code_code_hash_len"),
        sa.CheckConstraint("octet_length(nonce_hash) = 32", name="ck_app_auth_code_nonce_hash_len"),
        sa.PrimaryKeyConstraint("code_hash"),
    )
    op.create_index("ix_app_auth_code_expires_at", "app_auth_code", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_app_auth_code_expires_at", table_name="app_auth_code")
    op.drop_table("app_auth_code")
    op.drop_table("app_auth_consent")
