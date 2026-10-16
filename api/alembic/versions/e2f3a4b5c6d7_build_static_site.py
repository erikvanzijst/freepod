"""build static site

Adds ``build.static_site``: whether the build's image serves a static site with
Railpack's Caddy (static-site-sizing). Every existing build reads false, which
keeps the default request for whatever it runs until it is rebuilt.

Revision ID: e2f3a4b5c6d7
Revises: d4f1a8c3e2b7
Create Date: 2026-10-16

"""
from alembic import op
import sqlalchemy as sa


revision = "e2f3a4b5c6d7"
down_revision = "d4f1a8c3e2b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "build",
        sa.Column("static_site", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("build", "static_site")
