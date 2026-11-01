"""Bind user records to their Keycloak subject

Adds ``user.keycloak_subject``, the identity join key, nullable until a record
is adopted, and unique among non-deleted rows as ``uq_user_active`` makes the
email.

Revision ID: f3a8d1c6b9e2
Revises: c7e2a9d4f1b3
Create Date: 2026-11-01

"""
from alembic import op
import sqlalchemy as sa


revision = "f3a8d1c6b9e2"
down_revision = "c7e2a9d4f1b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user", sa.Column("keycloak_subject", sa.String(), nullable=True))
    op.create_index(
        "uq_user_keycloak_subject_active",
        "user",
        ["keycloak_subject"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_user_keycloak_subject_active", table_name="user")
    op.drop_column("user", "keycloak_subject")
