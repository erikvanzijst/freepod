from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query, Response
from sqlmodel import Session

from app.db import get_session
from app.deps import require_self
from app.models import UsageBucket, UsageDimension, UsageReport, UserORM
from app.services.errors import ValidationException
from app.services.usage import report as usage_report

router = APIRouter(prefix="/users/{user_id}/usage", tags=["usage"])


def _parse_csv_enum(raw: str, enum: type, name: str) -> set:
    values = {part.strip() for part in raw.split(",") if part.strip()}
    try:
        return {enum(value) for value in values}
    except ValueError:
        allowed = ", ".join(member.value for member in enum)
        raise ValidationException(f"{name} accepts a comma-separated subset of: {allowed}")


@router.get(
    "",
    response_model=UsageReport,
    summary="Report an account's resource usage and its cost",
    response_description="Usage per bucket and grouped dimension, as a table.",
    responses={
        200: {
            "description": "The report. With `Accept: text/csv`, the same table as CSV.",
            "content": {"text/csv": {}},
        },
        400: {"description": "Malformed range, bucket or grouping."},
        403: {"description": "Caller may only read their own usage."},
    },
)
def get_usage(
    user_id: int = Path(..., description="ID of the account whose usage is reported."),
    start: datetime | None = Query(
        None, description="Inclusive start. Defaults to the start of the current UTC month."
    ),
    end: datetime | None = Query(
        None, description="Exclusive end. Defaults to the start of the next UTC month."
    ),
    bucket: UsageBucket = Query(UsageBucket.DAY, description="Width of each row's window."),
    group_by: str = Query(
        "deployment,metric",
        description="Comma-separated dimensions to keep apart: `deployment`, `metric`. "
        "Dimensions left out are summed together; empty sums everything per bucket.",
    ),
    deployment_id: UUID | None = Query(None, description="Only this deployment."),
    metric: str | None = Query(
        None, description="Comma-separated metric names, e.g. `cpu_core_hours`."
    ),
    accept: str | None = Header(None, include_in_schema=False),
    _: UserORM = Depends(require_self),
    session: Session = Depends(get_session),
):
    """What an account's deployments consumed over a period, and what it costs.

    ## Authorization
    You may read your own usage; administrators may read any account's.

    ## Behavior
    Each row is one bucket (UTC) and one combination of the grouped dimensions.
    `columns` names the positions in each row: always `window_start` first and
    `cost` last, with `deployment_id`, `deployment_name`, `deployment_hostname`,
    `metric`, `unit` and `value` in between for whichever dimensions are
    grouped. `deployment_hostname` is null for a deployment that never had one. `value` is only
    present when grouping by `metric`: quantities in different units do not add
    up, only their costs do. Quantities and costs are exact, unrounded decimal
    strings; `currency` is the cost's.

    Only billable metrics are reported. Buckets with nothing recorded are absent
    rather than zero, and `recorded_through` is the end of the newest measured
    window, so usage after it is not yet known rather than zero. Deleted
    deployments' usage is included.

    Send `Accept: text/csv` for the same table as CSV.

    ## Errors
    - **400 Bad Request** — `end` not after `start`, too many buckets for the
      range, or an unknown `group_by` dimension.
    - **403 Forbidden** — reading another account's usage without
      administrator privileges.
    """
    default_start, default_end = usage_report.current_month()
    report = usage_report.query_usage(
        session,
        user_id=user_id,
        start=start or default_start,
        end=end or default_end,
        bucket=bucket,
        group_by=_parse_csv_enum(group_by, UsageDimension, "group_by"),
        deployment_id=deployment_id,
        metrics={m.strip() for m in metric.split(",") if m.strip()} if metric else None,
    )
    if accept and "text/csv" in accept:
        filename = f"usage-{user_id}-{report.start:%Y%m%d}-{report.end:%Y%m%d}.csv"
        return Response(
            usage_report.report_csv(report),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    return report
