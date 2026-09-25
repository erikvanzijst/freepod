"""Reading the usage ledger back: bucketed, grouped, and priced.

Prices are applied here, at read time, never stored with a sample: the ledger holds
quantities only, so a past period can be re-evaluated when rates change. A sample is
priced at the ``usage_rate`` row in effect at its ``window_start``; a metric with no
rate is not billable.

Only additive (``delta``) quantities are reported. A gauge summed across a bucket is
not in its catalogued unit, and nothing here needs one yet.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlmodel import Session, select

from app.models import (
    MetricKind,
    UsageBucket,
    UsageDimension,
    UsageMetricORM,
    UsageRateORM,
    UsageReport,
    UsageSampleORM,
)
from app.services.errors import ValidationException

CURRENCY = "EUR"


MAX_BUCKETS = 1000
_APPROX_BUCKET = {
    UsageBucket.HOUR: timedelta(hours=1),
    UsageBucket.DAY: timedelta(days=1),
    UsageBucket.WEEK: timedelta(weeks=1),
    UsageBucket.MONTH: timedelta(days=28),
}

# Output columns per dimension, and the SQL that produces them.
_DIMENSION_COLUMNS: dict[UsageDimension, tuple[tuple[str, str], ...]] = {
    UsageDimension.PRODUCT: (
        ("product_id", "p.id"),
        ("product_name", "p.name"),
    ),
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
    user_id: int | None,
    start: datetime,
    end: datetime,
    bucket: UsageBucket = UsageBucket.DAY,
    group_by: set[UsageDimension] | frozenset[UsageDimension] = frozenset(
        {UsageDimension.DEPLOYMENT, UsageDimension.METRIC}
    ),
    deployment_id: UUID | None = None,
    metrics: set[str] | None = None,
    billable_only: bool = True,
) -> UsageReport:
    """Usage over ``[start, end)``, summed per bucket and per grouped dimension.

    ``user_id`` narrows it to one account; ``None`` spans every account. Usage no
    deployment is attributed to (platform overhead) is never included. Grouping
    by deployment needs a single account or deployment in scope: across every
    account it would grow with the customer base.

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
    if UsageDimension.DEPLOYMENT in group_by and user_id is None and deployment_id is None:
        raise ValidationException(
            "grouping by deployment needs a user_id or deployment_id to scope it"
        )
    if (end - start) / _APPROX_BUCKET[bucket] > MAX_BUCKETS:
        raise ValidationException(
            f"too many {bucket.value} buckets between start and end "
            f"(at most {MAX_BUCKETS}); choose a coarser bucket"
        )

    dimension_columns = [
        column
        for dimension in UsageDimension
        if dimension in group_by
        for column in _DIMENSION_COLUMNS[dimension]
    ]
    select_dims = "".join(f", {expr} AS {name}" for name, expr in dimension_columns)
    group_dims = "".join(f", {expr}" for _, expr in dimension_columns)

    metric_ids = _reportable_metric_ids(session, names=metrics, billable_only=billable_only)
    filters = [
        "s.window_start >= :start",
        "s.window_start < :end",
        "s.metric_id = ANY(:metric_ids)",
    ]
    params: dict[str, object] = {
        "bucket": bucket.value,
        "start": start,
        "end": end,
        "metric_ids": metric_ids,
    }
    if user_id is not None:
        filters.append("d.user_id = :user_id")
        params["user_id"] = user_id
    if billable_only:
        filters.append("r.unit_price IS NOT NULL")
    if deployment_id is not None:
        filters.append("d.id = :deployment_id")
        params["deployment_id"] = deployment_id

    statement = text(
        f"""
        SELECT date_trunc(:bucket, s.window_start) AS window_start{select_dims},
               sum(s.value) AS value,
               sum(s.value * r.unit_price / r.per_quantity) AS cost
        FROM usage_sample s
        JOIN usage_metric m ON m.id = s.metric_id
        JOIN usage_subject sub ON sub.id = s.subject_id
        JOIN deployment d ON d.id = sub.deployment_id
        JOIN product_template_version t ON t.id = d.desired_template_id
        JOIN product p ON p.id = t.product_id
        LEFT JOIN LATERAL (
            SELECT rate.unit_price, rate.per_quantity FROM usage_rate rate
            WHERE rate.metric_id = s.metric_id AND rate.effective_from <= s.window_start
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


def _reportable_metric_ids(
    session: Session, *, names: set[str] | None, billable_only: bool
) -> list[int]:
    """The catalog ids a report reads: additive metrics, priced ones if billable.

    Resolved here rather than filtered in the report's SQL. The catalog and rate
    tables are too small ever to reach autovacuum's analyze threshold, so the
    planner guesses their selectivity; on prod that guess turned a hash join
    into a 4.7M-row nested loop. Filtering samples by id leans on
    ``usage_sample``'s own statistics instead.
    """
    statement = select(UsageMetricORM.id).where(UsageMetricORM.kind == MetricKind.DELTA)
    if names:
        statement = statement.where(UsageMetricORM.name.in_(sorted(names)))
    if billable_only:
        statement = statement.where(
            UsageMetricORM.id.in_(select(UsageRateORM.metric_id))
        )
    return sorted(session.exec(statement).all())


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
