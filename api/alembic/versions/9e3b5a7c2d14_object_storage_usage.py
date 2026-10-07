"""object storage usage

Catalogs a bucket's size in byte-hours and prices it. Consumption only: the plan's
storage allowance is constant per plan and not recorded. Purely additive.

The rate is market-based (about EUR 0.02 per GiB-month); see the meter-object-storage
design.

Revision ID: 9e3b5a7c2d14
Revises: 7d2e9f4a1c58
Create Date: 2026-10-07

"""
from alembic import op
import sqlalchemy as sa


revision = "9e3b5a7c2d14"
down_revision = "7d2e9f4a1c58"
branch_labels = None
depends_on = None


# (name, axis, unit, kind, role)
METRICS = [
    ("object_storage_byte_hours", "storage", "byte_hours", "delta", "usage"),
]

# (metric, effective_from, unit_price in EUR, per_quantity)
RATES = [
    ("object_storage_byte_hours", "2026-10-07", "0.0000274", str(2**30)),
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
