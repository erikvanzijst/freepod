"""Accept the maintenance power reason

Widens ``ck_deployment_power_reason`` to admit ``maintenance``
(migrate-deployment-storage).

Revision ID: c7e2a9d4f1b8
Revises: a4c1e7b9d2f6
Create Date: 2026-11-12

"""
from alembic import op


revision = "c7e2a9d4f1b8"
down_revision = "a4c1e7b9d2f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_deployment_power_reason", "deployment_power", type_="check")
    op.create_check_constraint(
        "ck_deployment_power_reason",
        "deployment_power",
        "reason IN ('manual', 'payment', 'maintenance')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_deployment_power_reason", "deployment_power", type_="check")
    op.create_check_constraint(
        "ck_deployment_power_reason",
        "deployment_power",
        "reason IN ('manual', 'payment')",
    )
