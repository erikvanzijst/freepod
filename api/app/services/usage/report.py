"""Reading the usage ledger back: bucketed, grouped, and priced.

Prices are applied here, at read time, never stored with a sample: the ledger holds
quantities only, so a past period can be re-evaluated when rates change. A sample is
priced at the rate in effect at its ``window_start``.

Only additive (``delta``) quantities are reported. A gauge summed across a bucket is
not in its catalogued unit, and nothing here needs one yet.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlmodel import Session, select

from app.models import UsageBucket, UsageDimension, UsageReport, UsageSampleORM
from app.services.errors import ValidationException

CURRENCY = "EUR"
GIB = Decimal(2**30)


@dataclass(frozen=True)
class Rate:
    """``unit_price`` buys ``per_quantity`` of the metric's catalogued unit."""

    metric: str
    effective_from: datetime
    unit_price: Decimal
    per_quantity: Decimal = Decimal(1)


# Interim: these move to a versioned rate table once a migration can ship. They
# mirror the OpenCost costModel in tf/deps/opencost/main.tf, whose RAM price is per
# GiB-hour. A metric with no rate here is not billable.
RATES: tuple[Rate, ...] = (
    Rate("cpu_core_hours", datetime(2026, 6, 1), Decimal("0.015437")),
    Rate("ram_byte_hours", datetime(2026, 6, 1), Decimal("0.002069"), GIB),
)


MAX_BUCKETS = 1000
_APPROX_BUCKET = {
    UsageBucket.HOUR: timedelta(hours=1),
    UsageBucket.DAY: timedelta(days=1),
    UsageBucket.WEEK: timedelta(weeks=1),
    UsageBucket.MONTH: timedelta(days=28),
}

# Output columns per dimension, and the SQL that produces them.
_DIMENSION_COLUMNS: dict[UsageDimension, tuple[tuple[str, str], ...]] = {
    UsageDimension.DEPLOYMENT: (
        ("deployment_id", "d.id"),
        ("deployment_name", "d.name"),
        ("deployment_hostname", "d.hostname"),
    ),
    UsageDimension.METRIC: (
        ("metric", "m.name"),
        ("unit", "m.unit"),
    ),
}


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _plain(value: Decimal | None) -> str | None:
    """Decimal as a positional string: exact, and never ``1E-11``."""
    if value is None:
        return None
    return format(value.normalize(), "f")


def query_usage(
    session: Session,
    *,
    user_id: int,
    start: datetime,
    end: datetime,
    bucket: UsageBucket = UsageBucket.DAY,
    group_by: set[UsageDimension] | frozenset[UsageDimension] = frozenset(
        {UsageDimension.DEPLOYMENT, UsageDimension.METRIC}
    ),
    deployment_id: UUID | None = None,
    metrics: set[str] | None = None,
    billable_only: bool = True,
    rates: tuple[Rate, ...] = RATES,
) -> UsageReport:
    """A user's usage over ``[start, end)``, summed per bucket and per grouped dimension.

    A sample belongs to the bucket its ``window_start`` falls in, UTC. Dimensions left
    out of ``group_by`` are summed together; without ``metric`` among them only
    ``cost`` is reported, since quantities in different units do not add.

    Buckets with no samples are absent rather than zero: the ledger distinguishes
    "not measured" from "measured as zero", and ``recorded_through`` says how far
    measurement has got.

    ``cost`` is unrounded; rounding belongs to whatever issues an invoice. It is null
    for a metric that carries no rate, which only appears when ``billable_only`` is
    off.

    Usage of deleted deployments is included: attribution survives deletion.
    """
    start, end = _naive_utc(start), _naive_utc(end)
    if end <= start:
        raise ValidationException("end must be after start")
    if (end - start) / _APPROX_BUCKET[bucket] > MAX_BUCKETS:
        raise ValidationException(
            f"too many {bucket.value} buckets between start and end "
            f"(at most {MAX_BUCKETS}); choose a coarser bucket"
        )

    dimension_columns = [
        column
        for dimension in (UsageDimension.DEPLOYMENT, UsageDimension.METRIC)
        if dimension in group_by
        for column in _DIMENSION_COLUMNS[dimension]
    ]
    select_dims = "".join(f", {expr} AS {name}" for name, expr in dimension_columns)
    group_dims = "".join(f", {expr}" for _, expr in dimension_columns)

    filters = [
        "s.window_start >= :start",
        "s.window_start < :end",
        "d.user_id = :user_id",
        "m.kind = 'delta'",
    ]
    params: dict[str, object] = {
        "bucket": bucket.value,
        "start": start,
        "end": end,
        "user_id": user_id,
        "rate_metric": [r.metric for r in rates],
        "rate_from": [r.effective_from for r in rates],
        "rate_price": [r.unit_price for r in rates],
        "rate_per": [r.per_quantity for r in rates],
    }
    if billable_only:
        filters.append("r.unit_price IS NOT NULL")
    if deployment_id is not None:
        filters.append("d.id = :deployment_id")
        params["deployment_id"] = deployment_id
    if metrics:
        filters.append("m.name = ANY(:metrics)")
        params["metrics"] = sorted(metrics)

    statement = text(
        f"""
        WITH rate AS (
            SELECT * FROM unnest(
                CAST(:rate_metric AS text[]),
                CAST(:rate_from AS timestamp[]),
                CAST(:rate_price AS numeric[]),
                CAST(:rate_per AS numeric[])
            ) AS r(metric, effective_from, unit_price, per_quantity)
        )
        SELECT date_trunc(:bucket, s.window_start) AS window_start{select_dims},
               sum(s.value) AS value,
               sum(s.value * r.unit_price / r.per_quantity) AS cost
        FROM usage_sample s
        JOIN usage_metric m ON m.id = s.metric_id
        JOIN usage_subject sub ON sub.id = s.subject_id
        JOIN deployment d ON d.id = sub.deployment_id
        LEFT JOIN LATERAL (
            SELECT rate.unit_price, rate.per_quantity FROM rate
            WHERE rate.metric = m.name AND rate.effective_from <= s.window_start
            ORDER BY rate.effective_from DESC
            LIMIT 1
        ) r ON true
        WHERE {" AND ".join(filters)}
        GROUP BY date_trunc(:bucket, s.window_start){group_dims}
        ORDER BY 1{group_dims}
        """
    )

    # Quantities in different units do not add up; only their costs do.
    value_columns = ["value", "cost"] if UsageDimension.METRIC in group_by else ["cost"]
    rows = [
        [
            row.window_start,
            *(getattr(row, name) for name, _ in dimension_columns),
            *(_plain(getattr(row, name)) for name in value_columns),
        ]
        for row in session.execute(statement, params)
    ]

    return UsageReport(
        user_id=user_id,
        start=start,
        end=end,
        bucket=bucket,
        currency=CURRENCY,
        recorded_through=recorded_through(session),
        columns=["window_start", *(name for name, _ in dimension_columns), *value_columns],
        rows=rows,
    )


def current_month(now: datetime | None = None) -> tuple[datetime, datetime]:
    """The calendar month containing ``now``, UTC, as ``[start, end)``."""
    now = now or datetime.now(UTC)
    start = datetime(now.year, now.month, 1)
    end = datetime(now.year + now.month // 12, now.month % 12 + 1, 1)
    return start, end


def recorded_through(session: Session) -> datetime | None:
    """End of the newest recorded window: how far measurement has got, ledger-wide."""
    newest = session.exec(
        select(UsageSampleORM.window_start, UsageSampleORM.interval_seconds)
        .order_by(UsageSampleORM.window_start.desc())
        .limit(1)
    ).first()
    if newest is None:
        return None
    return newest[0] + timedelta(seconds=newest[1])


def report_csv(report: UsageReport) -> str:
    """The report's rows as CSV, header first. Timestamps are ISO 8601 UTC."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(report.columns)
    for row in report.rows:
        writer.writerow(
            f"{cell.isoformat()}Z" if isinstance(cell, datetime) else cell
            for cell in row
        )
    return out.getvalue()
