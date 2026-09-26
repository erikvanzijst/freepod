"""The sampling loop: which windows to read, in what order, and when to stop.

Reading a window is `source`, naming what it contains is `mapping`, who owns it is
`subjects`, writing it is `ledger`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging

from sqlmodel import Session, select

from app.config import CaelusSettings, get_settings
from app.models import UsageSampleORM, UsageSubjectORM
from app.models.usage import SubjectKind
from app.services.usage import ledger, subjects
from app.services.usage.opencost import OpenCostClient
from app.services.usage.ledger import SampleRow
from app.services.usage.mapping import quantities
from app.services.usage.source import billable, read_window

logger = logging.getLogger(__name__)


@dataclass
class SampleRun:
    """What one pass did."""

    windows_recorded: int = 0
    windows_skipped: int = 0
    samples_written: int = 0
    skipped_reasons: list[str] = field(default_factory=list)


def align(moment: datetime, window_seconds: int) -> datetime:
    """Floor to the window grid."""
    epoch = datetime(1970, 1, 1)
    elapsed = int((moment - epoch).total_seconds())
    return epoch + timedelta(seconds=elapsed - elapsed % window_seconds)


def last_recorded_window(session: Session) -> datetime | None:
    """The newest window this sampler recorded, or None when it has recorded none.

    Only container subjects count: the build worker writes closed windows of its own,
    possibly ahead of a stalled sampler, and counting those would skip the windows in
    between for good.
    """
    return session.exec(
        select(UsageSampleORM.window_start)
        .join(UsageSubjectORM, UsageSubjectORM.id == UsageSampleORM.subject_id)
        .where(UsageSubjectORM.kind == SubjectKind.CONTAINER)
        .order_by(UsageSampleORM.window_start.desc())
        .limit(1)
    ).first()


def resume_from(
    session: Session, *, now: datetime, window_seconds: int, lookback_seconds: int
) -> datetime:
    """One window past what is recorded; a bounded lookback when nothing is."""
    recorded = last_recorded_window(session)
    if recorded is not None:
        return align(recorded, window_seconds) + timedelta(seconds=window_seconds)
    return align(now - timedelta(seconds=lookback_seconds), window_seconds)


def recordable_until(
    *, now: datetime, window_seconds: int, settle_seconds: int
) -> datetime:
    """Exclusive end of the range whose windows may be recorded.

    A window is eligible only once it has closed and the settling allowance elapsed.
    """
    return align(now - timedelta(seconds=settle_seconds), window_seconds)


def pending_windows(
    session: Session,
    *,
    now: datetime,
    window_seconds: int,
    settle_seconds: int,
    lookback_seconds: int,
    max_windows: int,
) -> list[datetime]:
    """The window starts to attempt this pass, oldest first and bounded.

    The remainder of a long gap is what the next pass finds still missing.
    """
    start = resume_from(
        session,
        now=now,
        window_seconds=window_seconds,
        lookback_seconds=lookback_seconds,
    )
    end = recordable_until(
        now=now, window_seconds=window_seconds, settle_seconds=settle_seconds
    )

    # Each window is derived from `start` directly rather than from its predecessor,
    # so no step can accumulate and every element stays on `start`'s grid.
    span = int((end - start).total_seconds())
    count = min(max_windows, max(0, span // window_seconds))
    return [start + timedelta(seconds=i * window_seconds) for i in range(count)]


def record_window(
    session: Session,
    client: OpenCostClient,
    window_start: datetime,
    *,
    window_seconds: int,
    observed_at: datetime,
    environment: str,
    builds_namespace: str | None = None,
    catalog: dict[str, int] | None = None,
) -> int | None:
    """Record one window. Returns samples written, or None if it was not usable.

    None means unmeasured and the position must not pass it; zero means measured and
    holding nothing new.
    """
    window_end = window_start + timedelta(seconds=window_seconds)
    reading = read_window(client, window_start, window_end)
    if not reading.is_usable:
        return None

    allocations = billable(
        reading.allocations, environment=environment, builds_namespace=builds_namespace
    )
    if not allocations:
        return None

    resolved = subjects.resolve_subjects(
        session, allocations, observed_at=observed_at
    )
    catalog = catalog if catalog is not None else ledger.metric_ids(session)

    rows: list[SampleRow] = []
    for allocation in allocations:
        subject_id = resolved[subjects.subject_ref(allocation)]
        for metric, value in quantities(allocation).items():
            rows.append(
                SampleRow(
                    subject_id=subject_id,
                    metric=metric,
                    window_start=window_start,
                    interval_seconds=reading.interval_seconds,
                    value=value,
                )
            )

    return ledger.record_samples(
        session, rows, observed_at=observed_at, catalog=catalog
    )


def sample_once(
    session: Session,
    client: OpenCostClient,
    *,
    now: datetime | None = None,
    settings: CaelusSettings | None = None,
) -> SampleRun:
    """One pass: record every eligible window, committing as it goes.

    An unmeasurable window stops the pass rather than being skipped: the position is
    `max(window_start)`, so recording past a gap would strand it permanently.
    """
    settings = settings or get_settings()
    now = now or _utcnow()
    result = SampleRun()

    windows = pending_windows(
        session,
        now=now,
        window_seconds=settings.usage_window_seconds,
        settle_seconds=settings.usage_settle_seconds,
        lookback_seconds=settings.usage_first_run_lookback_seconds,
        max_windows=settings.usage_max_windows_per_pass,
    )
    if not windows:
        return result

    catalog = ledger.metric_ids(session)
    for window_start in windows:
        written = record_window(
            session,
            client,
            window_start,
            window_seconds=settings.usage_window_seconds,
            observed_at=now,
            environment=settings.environment,
            builds_namespace=settings.builds_namespace,
            catalog=catalog,
        )
        if written is None:
            session.rollback()
            result.windows_skipped += 1
            result.skipped_reasons.append(window_start.isoformat())
            break
        session.commit()
        result.windows_recorded += 1
        result.samples_written += written

    logger.info(
        "Usage pass complete: recorded=%s samples=%s stopped_at=%s",
        result.windows_recorded,
        result.samples_written,
        result.skipped_reasons[0] if result.skipped_reasons else "-",
    )
    return result


def _utcnow() -> datetime:
    from datetime import UTC

    return datetime.now(UTC).replace(tzinfo=None)
