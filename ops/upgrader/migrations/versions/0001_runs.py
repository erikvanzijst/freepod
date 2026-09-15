"""Runs and product results

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("trigger", sa.String(16), nullable=False),
        sa.Column("scope", sa.String(64)),
        sa.Column("dry_run", sa.Boolean, nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("pi_version", sa.String(64)),
        sa.Column("model", sa.String(200)),
        sa.Column("thinking_level", sa.String(16)),
    )
    op.create_table(
        "product_results",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("run_id", sa.Integer, sa.ForeignKey("runs.id"), nullable=False, index=True),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("current_version", sa.String(200)),
        sa.Column("target_version", sa.String(200)),
        sa.Column("pr_url", sa.Text),
        sa.Column("draft", sa.Boolean),
        sa.Column("branch", sa.Text),
        sa.Column("skip_reason", sa.Text),
        sa.Column("needs_human", JSONB, nullable=False),
        sa.Column("error", sa.Text),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("input_tokens", sa.Integer),
        sa.Column("output_tokens", sa.Integer),
        sa.Column("peak_context", sa.Integer),
        sa.Column("commit", sa.String(64)),
        sa.Column("files", JSONB, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("product_results")
    op.drop_table("runs")
