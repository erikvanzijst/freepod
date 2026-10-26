"""app auth OIDC codes

Adds ``app_auth_oidc_code``, the authorization codes app-auth's OpenID
Provider issues to tenant apps, stored hashed. A table apart from
``app_auth_code``, so that neither kind of code redeems as the other.

Revision ID: a3c9e1f7b2d4
Revises: e5b2c7d9a1f4
Create Date: 2026-10-26

"""
from alembic import op
import sqlalchemy as sa


revision = "a3c9e1f7b2d4"
down_revision = "e5b2c7d9a1f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_auth_oidc_code",
        sa.Column("code_hash", sa.LargeBinary(), nullable=False),
        sa.Column("deployment_id", sa.Uuid(), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("nonce", sa.Text(), nullable=True),
        sa.Column("code_challenge", sa.Text(), nullable=True),
        sa.Column("auth_time", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("octet_length(code_hash) = 32", name="ck_app_auth_oidc_code_code_hash_len"),
        sa.ForeignKeyConstraint(["deployment_id"], ["deployment.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("code_hash"),
    )
    op.create_index("ix_app_auth_oidc_code_expires_at", "app_auth_oidc_code", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_app_auth_oidc_code_expires_at", table_name="app_auth_oidc_code")
    op.drop_table("app_auth_oidc_code")
