"""database storage usage

Catalogs a tenant database's size and its plan allowance, both in byte-hours, and prices
the size. Purely additive: no table changes.

The rate is market-based (about EUR 0.125 per GiB-month), unlike the at-cost CPU and RAM
rates; see the meter-relational-storage design.

Revision ID: 4b7e2c9d1a36
Revises: d71152c7e6ff
Create Date: 2026-10-06

"""
from alembic import op
import sqlalchemy as sa


revision = "4b7e2c9d1a36"
down_revision = "d71152c7e6ff"
branch_labels = None
depends_on = None


# (name, axis, unit, kind, role)
METRICS = [
    ("db_byte_hours", "storage", "byte_hours", "delta", "usage"),
    ("db_allowance_byte_hours", "storage", "byte_hours", "delta", "allocation"),
]

# (metric, effective_from, unit_price in EUR, per_quantity)
RATES = [
    ("db_byte_hours", "2026-10-06", "0.000171", str(2**30)),
]


def upgrade() -> None:
    for name, axis, unit, kind, role in METRICS:
        op.execute(
            sa.text(
                "INSERT INTO usage_metric (name, axis, unit, kind, role) "
                "VALUES (:name, :axis, :unit, :kind, :role)"
            ).bindparams(name=name, axis=axis, unit=unit, kind=kind, role=role)
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
    names = sa.bindparam("names", [name for name, *_ in METRICS], expanding=True)
    for table in ("usage_sample", "usage_rate"):
        op.execute(
            sa.text(
                f"DELETE FROM {table} WHERE metric_id IN "
                "(SELECT id FROM usage_metric WHERE name IN :names)"
            ).bindparams(names)
        )
    op.execute(sa.text("DELETE FROM usage_metric WHERE name IN :names").bindparams(names))
