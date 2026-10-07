"""usage_sample (metric_id, window_start)

Serves each sampler source's resume position, ``max(window_start)`` over the metrics only
that source records, as one backward index-only scan per metric, however far behind the
source is.

Built inside the migration's transaction rather than concurrently: ``CONCURRENTLY``
needs an autocommit block, which would commit the transaction holding the runner's
advisory lock. The table is small enough that the plain build is sub-second.

Revision ID: 7d2e9f4a1c58
Revises: 5c8f3d0e2b47
Create Date: 2026-10-07

"""
from alembic import op


revision = "7d2e9f4a1c58"
down_revision = "5c8f3d0e2b47"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_usage_sample_metric_window", "usage_sample", ["metric_id", "window_start"]
    )


def downgrade() -> None:
    op.drop_index("ix_usage_sample_metric_window", table_name="usage_sample")
