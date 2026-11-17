"""The repository a deployment is built from

Revision ID: f5ae9632f172
Revises: fa5a408a4483
Create Date: 2026-11-17

"""
from alembic import op
import sqlalchemy as sa


revision = "f5ae9632f172"
down_revision = "fa5a408a4483"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deployment_source",
        sa.Column(
            "deployment_id",
            sa.Uuid(),
            sa.ForeignKey("deployment.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("host", sa.String(253), nullable=False),
        sa.Column("repository_id", sa.String(64), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("branch", sa.String(255), nullable=False),
        sa.Column("root_dir", sa.String(1024), nullable=False, server_default=""),
        sa.Column("installation_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_deployment_source_repository",
        "deployment_source",
        ["provider", "host", "repository_id"],
    )


def downgrade() -> None:
    op.drop_table("deployment_source")
