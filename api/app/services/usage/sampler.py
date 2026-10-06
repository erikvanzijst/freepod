"""The sampling loop: which windows to read, in what order, and when to stop.

Each measurement source is walked on its own: its own resume position, its own first
unusable window, its own failures. Containers from OpenCost (`containers`) are one
source; tenant database sizes (`databases`) are another. A source yields observations;
`ledger` writes them, a chunk at a time.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from typing import Protocol

from sqlmodel import Session, select

from app.config import CaelusSettings, get_settings
from app.models import UsageSampleORM, UsageSubjectORM
from app.models.usage import SubjectKind
from app.services.usage import ledger
from app.services.usage.containers import OpenCostSource
from app.services.usage.databases import DatabaseSizeSource
from app.services.usage.ledger import Observation
from app.services.usage.opencost import OpenCostClient

logger = logging.getLogger(__name__)


@dataclass
class SampleRun:
    """What one pass did, summed over its sources."""

    windows_recorded: int = 0
    windows_skipped: int = 0
    samples_written: int = 0
    skipped_reasons: list[str] = field(default_factory=list)
    failed_sources: list[str] = field(default_factory=list)


class Source(Protocol):
    """One measurement source: what it records against, and how it reads a window."""

    name: str
    # Scopes the source's resume position to the subjects it records.
    subject_kind: SubjectKind

    def read(
        self, session: Session, window_start: datetime, *, window_seconds: int
    ) -> Iterable[Observation] | None:
        """The window's observations, or None when it is unusable.

        Decided before anything is yielded, so a source returns None eagerly and its
        observations lazily: the ledger consumes them a chunk at a time.
        """
        ...


def align(moment: datetime, window_seconds: int) -> datetime:
    """Floor to the window grid."""
    epoch = datetime(1970, 1, 1)
    elapsed = int((moment - epoch).total_seconds())
    return epoch + timedelta(seconds=elapsed - elapsed % window_seconds)


def last_recorded_window(
    session: Session, kind: SubjectKind = SubjectKind.CONTAINER
) -> datetime | None:
    """The newest window recorded for subjects of `kind`, or None when there is none.

    Scoped to one kind because other writers -- the build worker, and this sampler's
    other sources -- record closed windows of their own, possibly ahead of a stalled
    source, and counting those would skip the windows in between for good.
    """
    return session.exec(
        select(UsageSampleORM.window_start)
        .join(UsageSubjectORM, UsageSubjectORM.id == UsageSampleORM.subject_id)
        .where(UsageSubjectORM.kind == kind)
        .order_by(UsageSampleORM.window_start.desc())
        .limit(1)
    ).first()


def resume_from(
    session: Session,
    *,
    now: datetime,
    window_seconds: int,
    lookback_seconds: int,
    kind: SubjectKind = SubjectKind.CONTAINER,
) -> datetime:
    """One window past what is recorded; a bounded lookback when nothing is."""
    recorded = last_recorded_window(session, kind)
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
    kind: SubjectKind = SubjectKind.CONTAINER,
) -> list[datetime]:
    """The window starts to attempt this pass, oldest first and bounded.

    The remainder of a long gap is what the next pass finds still missing.
    """
    start = resume_from(
        session,
        now=now,
        window_seconds=window_seconds,
        lookback_seconds=lookback_seconds,
        kind=kind,
    )
    end = recordable_until(
        now=now, window_seconds=window_seconds, settle_seconds=settle_seconds
    )

    # Each window is derived from `start` directly rather than from its predecessor,
    # so no step can accumulate and every element stays on `start`'s grid.
    span = int((end - start).total_seconds())
    count = min(max_windows, max(0, span // window_seconds))
    return [start + timedelta(seconds=i * window_seconds) for i in range(count)]


def record_source_window(
    session: Session,
    source: Source,
    window_start: datetime,
    *,
    window_seconds: int,
    observed_at: datetime,
    catalog: dict[str, int] | None = None,
) -> int | None:
    """Record one window from `source`. Returns samples written, or None if unusable.

    None means unmeasured and the position must not pass it; zero means measured and
    holding nothing new.
    """
    observations = source.read(session, window_start, window_seconds=window_seconds)
    if observations is None:
        return None
    return ledger.record_observations(
        session,
        observations,
        window_start=window_start,
        interval_seconds=window_seconds,
        observed_at=observed_at,
        catalog=catalog,
    )


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
    """Record one OpenCost window. See `record_source_window`."""
    return record_source_window(
        session,
        OpenCostSource(client, environment=environment, builds_namespace=builds_namespace),
        window_start,
        window_seconds=window_seconds,
        observed_at=observed_at,
        catalog=catalog,
    )


def default_sources(
    client: OpenCostClient, settings: CaelusSettings
) -> list[Source]:
    """OpenCost always; tenant database sizes when their namespace is configured."""
    sources: list[Source] = [
        OpenCostSource(
            client,
            environment=settings.environment,
            builds_namespace=settings.builds_namespace,
        )
    ]
    if settings.usage_tenant_db_namespace:
        sources.append(DatabaseSizeSource.from_settings(settings))
    return sources


def _sample_source(
    session: Session,
    source: Source,
    *,
    now: datetime,
    settings: CaelusSettings,
    catalog: dict[str, int],
    result: SampleRun,
) -> None:
    """Record every eligible window of one source, committing as it goes.

    An unmeasurable window stops this source rather than being skipped: its position
    is `max(window_start)`, so recording past a gap would strand it permanently.
    """
    windows = pending_windows(
        session,
        now=now,
        window_seconds=settings.usage_window_seconds,
        settle_seconds=settings.usage_settle_seconds,
        lookback_seconds=settings.usage_first_run_lookback_seconds,
        max_windows=settings.usage_max_windows_per_pass,
        kind=source.subject_kind,
    )
    for window_start in windows:
        written = record_source_window(
            session,
            source,
            window_start,
            window_seconds=settings.usage_window_seconds,
            observed_at=now,
            catalog=catalog,
        )
        if written is None:
            session.rollback()
            result.windows_skipped += 1
            result.skipped_reasons.append(f"{source.name}:{window_start.isoformat()}")
            break
        session.commit()
        result.windows_recorded += 1
        result.samples_written += written


def sample_once(
    session: Session,
    client: OpenCostClient,
    *,
    now: datetime | None = None,
    settings: CaelusSettings | None = None,
    sources: list[Source] | None = None,
) -> SampleRun:
    """One pass: every source, each from its own position.

    A source that raises is logged and skipped for this pass; the others still run.
    """
    settings = settings or get_settings()
    now = now or _utcnow()
    sources = sources if sources is not None else default_sources(client, settings)
    result = SampleRun()

    catalog = ledger.metric_ids(session)
    for source in sources:
        try:
            _sample_source(
                session, source, now=now, settings=settings, catalog=catalog, result=result
            )
        except Exception:
            session.rollback()
            logger.exception("Usage source %s failed; retrying next pass", source.name)
            result.failed_sources.append(source.name)

    if not (result.windows_recorded or result.windows_skipped or result.failed_sources):
        return result
    logger.info(
        "Usage pass complete: recorded=%s samples=%s stopped_at=%s failed=%s",
        result.windows_recorded,
        result.samples_written,
        ",".join(result.skipped_reasons) or "-",
        ",".join(result.failed_sources) or "-",
    )
    return result


def _utcnow() -> datetime:
    from datetime import UTC

    return datetime.now(UTC).replace(tzinfo=None)
