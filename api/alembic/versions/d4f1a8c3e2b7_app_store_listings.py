"""Store-listing fields, template versions and product releases

Revision ID: d4f1a8c3e2b7
Revises: c2e3d9b293fb
Create Date: 2026-10-12

Adds the listing columns on `product` (product-listing-metadata), the
`version` column on `product_template_version` with the index behind
availability dates, and the `product_release` table (product-releases).
Existing rows get null text, empty lists and null versions; the catalog
reconciler fills in derivable versions on its next run.

"""

import sqlalchemy as sa
from alembic import op


revision = "d4f1a8c3e2b7"
down_revision = "c2e3d9b293fb"
branch_labels = None
depends_on = None

_LIST_COLUMNS = ("features", "links", "screenshots")


def upgrade() -> None:
    op.add_column("product", sa.Column("tagline", sa.String(), nullable=True))
    op.add_column("product", sa.Column("license", sa.Text(), nullable=True))
    for name in _LIST_COLUMNS:
        op.add_column(
            "product",
            sa.Column(name, sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        )

    op.add_column("product_template_version", sa.Column("version", sa.Text(), nullable=True))
    op.create_index(
        "ix_product_template_version_product_version",
        "product_template_version",
        ["product_id", "version"],
    )

    op.create_table(
        "product_release",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("product.id"), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("product_id", "version", name="uq_product_release_product_version"),
    )


def downgrade() -> None:
    op.drop_table("product_release")
    op.drop_index(
        "ix_product_template_version_product_version", table_name="product_template_version"
    )
    op.drop_column("product_template_version", "version")
    for name in reversed(_LIST_COLUMNS):
        op.drop_column("product", name)
    op.drop_column("product", "license")
    op.drop_column("product", "tagline")
