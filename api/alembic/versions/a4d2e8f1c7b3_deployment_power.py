"""Record deployment power in a ledger

Adds ``deployment_power``, one append-only row per requested stop or start,
and the nullable ``deployment.desired_power_id`` / ``applied_power_id``
pointers into it. Null means running, so existing deployments need no row.

Revision ID: a4d2e8f1c7b3
Revises: f3a8d1c6b9e2
Create Date: 2026-11-06

"""
from alembic import op
import sqlalchemy as sa


revision = "a4d2e8f1c7b3"
down_revision = "f3a8d1c6b9e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deployment_power",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "deployment_id",
            sa.Uuid(),
            sa.ForeignKey("deployment.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint("state IN ('running', 'stopped')", name="ck_deployment_power_state"),
        sa.CheckConstraint("reason IN ('manual', 'payment')", name="ck_deployment_power_reason"),
    )
    op.create_index(
        "ix_deployment_power_deployment", "deployment_power", ["deployment_id", "id"]
    )
    op.add_column("deployment", sa.Column("desired_power_id", sa.Integer(), nullable=True))
    op.add_column("deployment", sa.Column("applied_power_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_deployment_desired_power_id", "deployment", "deployment_power",
        ["desired_power_id"], ["id"],
    )
    op.create_foreign_key(
        "fk_deployment_applied_power_id", "deployment", "deployment_power",
        ["applied_power_id"], ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_deployment_applied_power_id", "deployment", type_="foreignkey")
    op.drop_constraint("fk_deployment_desired_power_id", "deployment", type_="foreignkey")
    op.drop_column("deployment", "applied_power_id")
    op.drop_column("deployment", "desired_power_id")
    op.drop_index("ix_deployment_power_deployment", table_name="deployment_power")
    op.drop_table("deployment_power")
