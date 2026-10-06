"""unique deployment_database.db_name

The usage sampler joins Prometheus's per-database series to ``deployment_database`` by
name, a chunk at a time; without an index every chunk is a sequential scan. Unique
because the name is derived from the deployment id and a deployment has one row.

Revision ID: 5c8f3d0e2b47
Revises: 4b7e2c9d1a36
Create Date: 2026-10-06

"""
from alembic import op


revision = "5c8f3d0e2b47"
down_revision = "4b7e2c9d1a36"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_deployment_database_db_name", "deployment_database", ["db_name"], unique=True
    )


def downgrade() -> None:
    op.drop_index("uq_deployment_database_db_name", table_name="deployment_database")
