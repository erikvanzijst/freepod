"""admin notice kinds

Seeds ``admin.account_created`` and ``admin.deployment_created``, which the API
queues to every administrator when an account or a deployment is created.

Revision ID: d86c6c300c10
Revises: b7e3f19a4c2d
Create Date: 2026-11-10

"""
from alembic import op


revision = "d86c6c300c10"
down_revision = "b7e3f19a4c2d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO notification_kind (kind, unsubscribable) VALUES "
        "('admin.account_created', true), ('admin.deployment_created', true)"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM notification_kind WHERE kind IN ('admin.account_created', 'admin.deployment_created')"
    )
