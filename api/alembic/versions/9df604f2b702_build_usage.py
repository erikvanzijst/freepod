"""build usage

Adds the build container's own usage report to ``build``, and ``usage_recorded_at``
marking when a build's samples reached the usage ledger. Every build already in a
terminal status is marked recorded here, so builds that ran before recording existed
are never written to the ledger, and never billed.

Revision ID: 9df604f2b702
Revises: da4841625b1f
Create Date: 2026-09-26

"""
from alembic import op
import sqlalchemy as sa


revision = "9df604f2b702"
down_revision = "da4841625b1f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("build", sa.Column("usage_cpu_seconds", sa.Double(), nullable=True))
    op.add_column(
        "build", sa.Column("usage_memory_byte_seconds", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "build", sa.Column("usage_memory_peak_bytes", sa.BigInteger(), nullable=True)
    )
    op.add_column("build", sa.Column("usage_started_at", sa.DateTime(), nullable=True))
    op.add_column("build", sa.Column("usage_finished_at", sa.DateTime(), nullable=True))
    op.add_column("build", sa.Column("usage_recorded_at", sa.DateTime(), nullable=True))

    op.execute(
        "UPDATE build SET usage_recorded_at = now() AT TIME ZONE 'UTC' "
        "WHERE status IN ('succeeded', 'failed', 'canceled')"
    )

    op.create_index(
        "ix_build_usage_pending",
        "build",
        ["finished_at"],
        postgresql_where=sa.text("usage_recorded_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_build_usage_pending", table_name="build")
    op.drop_column("build", "usage_recorded_at")
    op.drop_column("build", "usage_finished_at")
    op.drop_column("build", "usage_started_at")
    op.drop_column("build", "usage_memory_peak_bytes")
    op.drop_column("build", "usage_memory_byte_seconds")
    op.drop_column("build", "usage_cpu_seconds")
