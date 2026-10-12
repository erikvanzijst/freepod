"""Add 'unlisted' to product visibility

Revision ID: c2e3d9b293fb
Revises: 9e3b5a7c2d14
Create Date: 2026-10-12

Adds the value without touching any row. It runs inside the upgrade
transaction rather than in an autocommit block, which would release the
migration advisory lock (unlisted-product-visibility design D3); so no later
revision in the same upgrade may write 'unlisted'.

Downgrade moves unlisted products to 'public', keeping them reachable through
the API, then rebuilds the type without the value.

"""

from alembic import op


revision = "c2e3d9b293fb"
down_revision = "9e3b5a7c2d14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE productvisibility ADD VALUE IF NOT EXISTS 'unlisted'")


def downgrade() -> None:
    op.execute("UPDATE product SET visibility = 'public' WHERE visibility = 'unlisted'")
    op.execute("ALTER TYPE productvisibility RENAME TO productvisibility_old")
    op.execute("CREATE TYPE productvisibility AS ENUM ('public', 'admin')")
    op.execute("ALTER TABLE product ALTER COLUMN visibility DROP DEFAULT")
    op.execute(
        "ALTER TABLE product ALTER COLUMN visibility TYPE productvisibility "
        "USING visibility::text::productvisibility"
    )
    op.execute("ALTER TABLE product ALTER COLUMN visibility SET DEFAULT 'admin'")
    op.execute("DROP TYPE productvisibility_old")
