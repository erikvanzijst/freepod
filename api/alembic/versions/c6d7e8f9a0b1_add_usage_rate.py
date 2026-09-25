"""add usage rates

What a catalogued quantity costs, and from when. A sample is priced at read time at
the rate in effect at its window start, so a rate change is a new row and never
re-prices the past. Purely additive; rolling back drops the table.

Seeded with the rates the report used as constants, which mirror the OpenCost
costModel: CPU per core-hour, and RAM per GiB-hour against a ledger that records
byte-hours, hence ``per_quantity``.

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-09-25

"""
from alembic import op
import sqlalchemy as sa


revision = "c6d7e8f9a0b1"
down_revision = "b5c6d7e8f9a0"
branch_labels = None
depends_on = None


# (metric, effective_from, unit_price in EUR, per_quantity)
RATES = [
    ("cpu_core_hours", "2026-06-01", "0.015437", "1"),
    ("ram_byte_hours", "2026-06-01", "0.002069", str(2**30)),
]


def upgrade() -> None:
    op.create_table(
        "usage_rate",
        sa.Column("metric_id", sa.SmallInteger(), nullable=False),
        sa.Column("effective_from", sa.DateTime(), nullable=False),
        sa.Column("unit_price", sa.Numeric(), nullable=False),
        sa.Column(
            "per_quantity", sa.Numeric(), nullable=False, server_default=sa.text("1")
        ),
        sa.ForeignKeyConstraint(["metric_id"], ["usage_metric.id"]),
        sa.PrimaryKeyConstraint("metric_id", "effective_from"),
        sa.CheckConstraint("unit_price >= 0", name="ck_usage_rate_unit_price"),
        sa.CheckConstraint("per_quantity > 0", name="ck_usage_rate_per_quantity"),
    )
    for metric, effective_from, unit_price, per_quantity in RATES:
        op.execute(
            sa.text(
                "INSERT INTO usage_rate (metric_id, effective_from, unit_price, per_quantity) "
                "SELECT id, CAST(:effective_from AS timestamp), CAST(:unit_price AS numeric), "
                "CAST(:per_quantity AS numeric) FROM usage_metric WHERE name = :metric"
            ).bindparams(
                metric=metric,
                effective_from=effective_from,
                unit_price=unit_price,
                per_quantity=per_quantity,
            )
        )


def downgrade() -> None:
    op.drop_table("usage_rate")
