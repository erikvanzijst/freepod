"""Drop the account storage class

New deployments record the environment's class (openspec
default-storage-class D2). The downgrade re-adds the column empty.

Revision ID: e3b9c5d1a7f4
Revises: c7e2a9d4f1b8
Create Date: 2026-11-14

"""
from alembic import op
import sqlalchemy as sa


revision = "e3b9c5d1a7f4"
down_revision = "c7e2a9d4f1b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("user", "storage_class")


def downgrade() -> None:
    op.add_column("user", sa.Column("storage_class", sa.String(), nullable=True))
