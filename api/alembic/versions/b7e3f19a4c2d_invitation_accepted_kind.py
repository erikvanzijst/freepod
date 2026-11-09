"""invitation accepted kind

Seeds ``access.invitation_accepted``, which app-auth queues to a deployment's
owner when someone on its access list first signs in with their entry.

Revision ID: b7e3f19a4c2d
Revises: 6c56968ccaab
Create Date: 2026-11-09

"""
from alembic import op


revision = "b7e3f19a4c2d"
down_revision = "6c56968ccaab"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO notification_kind (kind, unsubscribable) VALUES ('access.invitation_accepted', true)"
    )


def downgrade() -> None:
    op.execute("DELETE FROM notification_kind WHERE kind = 'access.invitation_accepted'")
