"""add the usage ledger

Three tables plus the ``usage_amount`` view. Purely additive: nothing reads them, and
rolling back drops them.

The catalog is seeded here rather than by the worker, so there is no window in which a
deployment could write an uncatalogued quantity. A new quantity is a later migration
inserting a row, not a schema change.

Revision ID: b5c6d7e8f9a0
Revises: f3a4b5c6d7e8
Create Date: 2026-09-23

"""
from alembic import op
import sqlalchemy as sa


revision = "b5c6d7e8f9a0"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None


# (name, axis, unit, kind, role); design.md's mapping table says which OpenCost field
# each one reads.
METRICS = [
    ("cpu_core_hours", "cpu", "core_hours", "delta", "usage"),
    ("cpu_usage_cores_avg", "cpu", "cores", "gauge", "usage"),
    ("cpu_request_cores_avg", "cpu", "cores", "gauge", "allocation"),
    ("cpu_limit_cores_avg", "cpu", "cores", "gauge", "allocation"),
    ("ram_byte_hours", "memory", "byte_hours", "delta", "usage"),
    ("ram_usage_bytes_avg", "memory", "bytes", "gauge", "usage"),
    ("ram_request_bytes_avg", "memory", "bytes", "gauge", "allocation"),
    ("ram_limit_bytes_avg", "memory", "bytes", "gauge", "allocation"),
    ("network_transmit_bytes", "network", "bytes", "delta", "usage"),
    ("network_receive_bytes", "network", "bytes", "delta", "usage"),
    ("pv_byte_hours", "storage", "byte_hours", "delta", "allocation"),
    ("running_seconds", "runtime", "seconds", "delta", "usage"),
]


def upgrade() -> None:
    usage_metric = op.create_table(
        "usage_metric",
        sa.Column(
            "id",
            sa.SmallInteger(),
            sa.Identity(always=True),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("axis", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "usage_subject",
        sa.Column(
            "id",
            sa.Integer(),
            sa.Identity(always=True),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("ref", sa.Text(), nullable=False),
        sa.Column("namespace", sa.String(), nullable=True),
        sa.Column("deployment_id", sa.Uuid(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        # No cascade: attribution outlives the deployment row.
        sa.ForeignKeyConstraint(["deployment_id"], ["deployment.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "ref", name="uq_usage_subject_kind_ref"),
    )
    op.create_index(
        "ix_usage_subject_deployment",
        "usage_subject",
        ["deployment_id"],
        postgresql_where=sa.text("deployment_id IS NOT NULL"),
    )
    op.create_index("ix_usage_subject_namespace", "usage_subject", ["namespace"])

    op.create_table(
        "usage_sample",
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("metric_id", sa.SmallInteger(), nullable=False),
        sa.Column("window_start", sa.DateTime(), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("value", sa.Numeric(), nullable=False),
        sa.ForeignKeyConstraint(["metric_id"], ["usage_metric.id"]),
        sa.ForeignKeyConstraint(["subject_id"], ["usage_subject.id"]),
        sa.PrimaryKeyConstraint("subject_id", "metric_id", "window_start"),
    )
    op.create_index("ix_usage_sample_window", "usage_sample", ["window_start"])

    op.bulk_insert(
        usage_metric,
        [
            {"name": name, "axis": axis, "unit": unit, "kind": kind, "role": role}
            for name, axis, unit, kind, role in METRICS
        ],
    )

    op.execute(
        """
        CREATE VIEW usage_amount AS
        SELECT s.subject_id, s.window_start, s.interval_seconds,
               m.name AS metric, m.axis, m.role,
               CASE m.kind WHEN 'gauge' THEN s.value * s.interval_seconds
                           ELSE s.value END AS amount
        FROM usage_sample s JOIN usage_metric m ON m.id = s.metric_id
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW usage_amount")
    op.drop_index("ix_usage_sample_window", table_name="usage_sample")
    op.drop_table("usage_sample")
    op.drop_index("ix_usage_subject_namespace", table_name="usage_subject")
    op.drop_index("ix_usage_subject_deployment", table_name="usage_subject")
    op.drop_table("usage_subject")
    op.drop_table("usage_metric")
