"""Record a storage class per account and per deployment

Adds nullable ``user.storage_class`` and ``deployment.storage_class``. No
backfill: existing rows read null (openspec deployment-storage-class D1).

Revision ID: a4c1e7b9d2f6
Revises: d86c6c300c10
Create Date: 2026-11-11

"""
from alembic import op
import sqlalchemy as sa


revision = "a4c1e7b9d2f6"
down_revision = "d86c6c300c10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user", sa.Column("storage_class", sa.String(), nullable=True))
    op.add_column("deployment", sa.Column("storage_class", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("deployment", "storage_class")
    op.drop_column("user", "storage_class")
