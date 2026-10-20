"""Rename the account subdomain to the account handle

Revision ID: e5b2c7d9a1f4
Revises: d4f1a8c3e2b7
Create Date: 2026-10-20

Tenant hostnames are `<app>-<handle>.<tenant domain>`, so what an account
holds is a handle rather than a subdomain. Values are kept as they are: every
held subdomain already fits the handle's format.

"""

import sqlalchemy as sa
from alembic import op


revision = "e5b2c7d9a1f4"
down_revision = "d4f1a8c3e2b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("uq_user_subdomain_active", table_name="user")
    op.alter_column("user", "subdomain", new_column_name="handle")
    op.create_index(
        "uq_user_handle_active",
        "user",
        [sa.text("lower(handle)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_user_handle_active", table_name="user")
    op.alter_column("user", "handle", new_column_name="subdomain")
    op.create_index(
        "uq_user_subdomain_active",
        "user",
        [sa.text("lower(subdomain)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
