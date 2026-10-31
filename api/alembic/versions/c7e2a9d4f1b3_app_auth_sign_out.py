"""app auth sign-out

Adds ``app_auth_sign_in``, the OIDC sign-ins of each Keycloak session, and
``app_auth_ended_session``, the Keycloak sessions that have ended, so that a
sign-out reaches every app the browser signed in to. Sign-in codes gain the
Keycloak session they were issued in, and OIDC codes the ``sid`` given to the
app.

Revision ID: c7e2a9d4f1b3
Revises: b4d8f2a6c1e9
Create Date: 2026-10-30

"""
from alembic import op
import sqlalchemy as sa


revision = "c7e2a9d4f1b3"
down_revision = "b4d8f2a6c1e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_auth_code", sa.Column("keycloak_sid", sa.Text(), nullable=True))
    op.add_column("app_auth_oidc_code", sa.Column("sid", sa.Text(), nullable=True))
    op.create_table(
        "app_auth_sign_in",
        sa.Column("keycloak_sid", sa.Text(), nullable=False),
        sa.Column("deployment_id", sa.Uuid(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("sid", sa.Text(), nullable=False),
        sa.Column("signed_in_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["deployment_id"], ["deployment.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("keycloak_sid", "deployment_id"),
    )
    op.create_index("ix_app_auth_sign_in_signed_in_at", "app_auth_sign_in", ["signed_in_at"])
    op.create_table(
        "app_auth_ended_session",
        sa.Column("keycloak_sid", sa.Text(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("keycloak_sid"),
    )
    op.create_index("ix_app_auth_ended_session_ended_at", "app_auth_ended_session", ["ended_at"])


def downgrade() -> None:
    op.drop_index("ix_app_auth_ended_session_ended_at", table_name="app_auth_ended_session")
    op.drop_table("app_auth_ended_session")
    op.drop_index("ix_app_auth_sign_in_signed_in_at", table_name="app_auth_sign_in")
    op.drop_table("app_auth_sign_in")
    op.drop_column("app_auth_oidc_code", "sid")
    op.drop_column("app_auth_code", "keycloak_sid")
