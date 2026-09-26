"""A build's usage in the ledger: computed from the build row alone, written once.

The build worker stores what a build's container measured about itself when the build
finishes; this turns that into samples once every window the run spans has settled.
Nothing here holds state between passes: the pending set is the builds whose
`usage_recorded_at` is null, and writing the samples and the mark is one transaction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func
from sqlmodel import Session, select

from app.config import CaelusSettings, get_settings
from app.models import BuildORM
from app.models.usage import SubjectKind
from app.services import build_jobs
from app.services.build_constants import BUILD_STATUS_FAILED, BUILD_STATUS_SUCCEEDED
from app.services.usage import ledger, subjects
from app.services.usage.ledger import SampleRow
from app.services.usage.sampler import align

logger = logging.getLogger(__name__)

SECONDS_PER_HOUR = Decimal(3600)

_BINARY_SUFFIXES = {"Ki": 1 << 10, "Mi": 1 << 20, "Gi": 1 << 30, "Ti": 1 << 40}


def cores(quantity: str) -> Decimal:
    """A Kubernetes CPU quantity, in cores."""
    if quantity.endswith("m"):
        return Decimal(quantity[:-1]) / 1000
    return Decimal(quantity)


def byte_count(quantity: str) -> Decimal:
    """A Kubernetes memory quantity, in bytes. Only the forms the Job uses."""
    for suffix, factor in _BINARY_SUFFIXES.items():
        if quantity.endswith(suffix):
            return Decimal(quantity[: -len(suffix)]) * factor
    return Decimal(quantity)


# The build Job's envelope, read from the manifest's own constants so the two
# cannot disagree.
CPU_REQUEST_CORES = cores(build_jobs.CPU_REQUEST)
CPU_LIMIT_CORES = cores(build_jobs.CPU_LIMIT)
MEMORY_REQUEST_BYTES = byte_count(build_jobs.MEMORY_REQUEST)
MEMORY_LIMIT_BYTES = byte_count(build_jobs.MEMORY_LIMIT)


@dataclass(frozen=True)
class WindowUsage:
    window_start: datetime
    quantities: dict[str, Decimal]


def _naive_utc(moment: datetime) -> datetime:
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC).replace(tzinfo=None)
    return moment


def _seconds(delta: timedelta) -> Decimal:
    """Exact, unlike `total_seconds()`."""
    return Decimal(delta // timedelta(microseconds=1)) / 1_000_000


def is_measured(build: BuildORM) -> bool:
    """Whether the build reported its usage; the worker stores all of it or none."""
    return None not in (
        build.usage_cpu_seconds,
        build.usage_memory_byte_seconds,
        build.usage_started_at,
        build.usage_finished_at,
    )


def run_of(build: BuildORM) -> tuple[datetime, datetime] | None:
    """The run to record: the container's own when it reported, else the worker's."""
    if is_measured(build):
        start, end = build.usage_started_at, build.usage_finished_at
    else:
        start, end = build.started_at, build.finished_at
    if start is None or end is None:
        return None
    return _naive_utc(start), _naive_utc(end)


def window_quantities(build: BuildORM, *, window_seconds: int) -> list[WindowUsage]:
    """Each window's share of the build's usage, in proportion to the run within it.

    Billable CPU and memory are floored at the requests held for that share. Averages
    are over the whole run, as OpenCost reports them for every container in the ledger.
    An estimated build records no usage averages: nothing was measured.
    """
    run = run_of(build)
    if run is None or run[1] <= run[0]:
        return []
    start, end = run
    wall = _seconds(end - start)
    measured = is_measured(build)
    if measured:
        cpu_seconds = Decimal(str(build.usage_cpu_seconds))
        memory_byte_seconds = Decimal(build.usage_memory_byte_seconds)

    step = timedelta(seconds=window_seconds)
    windows: list[WindowUsage] = []
    window_start = align(start, window_seconds)
    while window_start < end:
        overlap = _seconds(min(end, window_start + step) - max(start, window_start))
        share = overlap / wall
        hours = overlap / SECONDS_PER_HOUR
        cpu_floor = CPU_REQUEST_CORES * hours
        memory_floor = MEMORY_REQUEST_BYTES * hours
        quantities = {
            "cpu_request_cores_avg": CPU_REQUEST_CORES,
            "cpu_limit_cores_avg": CPU_LIMIT_CORES,
            "ram_request_bytes_avg": MEMORY_REQUEST_BYTES,
            "ram_limit_bytes_avg": MEMORY_LIMIT_BYTES,
            "running_seconds": overlap,
        }
        if measured:
            quantities |= {
                "cpu_core_hours": max(cpu_floor, cpu_seconds * share / SECONDS_PER_HOUR),
                "ram_byte_hours": max(
                    memory_floor, memory_byte_seconds * share / SECONDS_PER_HOUR
                ),
                "cpu_usage_cores_avg": cpu_seconds / wall,
                "ram_usage_bytes_avg": memory_byte_seconds / wall,
            }
        else:
            quantities |= {"cpu_core_hours": cpu_floor, "ram_byte_hours": memory_floor}
        windows.append(WindowUsage(window_start=window_start, quantities=quantities))
        window_start += step
    return windows


@dataclass
class RecordRun:
    """What one recording pass did."""

    builds_recorded: int = 0
    samples_written: int = 0
    failed: list[UUID] = field(default_factory=list)


def _next_pending(
    session: Session, *, settled_before: datetime, exclude: list[UUID]
) -> BuildORM | None:
    """The oldest finished build whose windows have all settled, locked for recording.

    `greatest` takes the later of the two ends, so a container clock running ahead
    of the worker's cannot bring a build in early. SKIP LOCKED lets a concurrent
    pass step over a build being recorded; once committed, it no longer matches.
    """
    statement = (
        select(BuildORM)
        .where(
            BuildORM.status.in_((BUILD_STATUS_SUCCEEDED, BUILD_STATUS_FAILED)),
            BuildORM.job_id.isnot(None),
            BuildORM.usage_recorded_at.is_(None),
            func.greatest(BuildORM.finished_at, BuildORM.usage_finished_at) < settled_before,
        )
        .order_by(BuildORM.finished_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if exclude:
        statement = statement.where(BuildORM.id.not_in(exclude))
    return session.exec(statement).first()


def record_build(
    session: Session,
    build: BuildORM,
    *,
    now: datetime,
    settings: CaelusSettings,
    catalog: dict[str, int],
) -> int:
    """Write one build's subject and samples and mark it recorded. Does not commit."""
    rows: list[SampleRow] = []
    windows = window_quantities(build, window_seconds=settings.usage_window_seconds)
    if windows:
        subject_id = subjects.upsert_subject(
            session,
            kind=SubjectKind.BUILD,
            ref=str(build.id),
            namespace=settings.builds_namespace,
            deployment_id=build.deployment_id,
            observed_at=now,
        )
        rows = [
            SampleRow(
                subject_id=subject_id,
                metric=metric,
                window_start=window.window_start,
                interval_seconds=settings.usage_window_seconds,
                value=value,
            )
            for window in windows
            for metric, value in window.quantities.items()
        ]
    written = ledger.record_samples(session, rows, observed_at=now, catalog=catalog)
    build.usage_recorded_at = now
    session.add(build)
    return written


def record_settled_builds(
    session: Session,
    *,
    now: datetime | None = None,
    settings: CaelusSettings | None = None,
    max_builds: int = 100,
) -> RecordRun:
    """Record every finished build whose windows have closed and settled.

    One transaction per build, so a crash loses at most the build in hand, and that
    build's samples and mark together. A build that fails to record is skipped for
    the rest of this pass and retried on the next.
    """
    settings = settings or get_settings()
    now = _naive_utc(now or datetime.now(UTC))
    result = RecordRun()
    settled_before = align(
        now - timedelta(seconds=settings.usage_settle_seconds),
        settings.usage_window_seconds,
    )
    catalog = ledger.metric_ids(session)

    for _ in range(max_builds):
        build = _next_pending(session, settled_before=settled_before, exclude=result.failed)
        if build is None:
            break
        build_id = build.id
        try:
            written = record_build(session, build, now=now, settings=settings, catalog=catalog)
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("Failed to record usage for build id=%s", build_id)
            result.failed.append(build_id)
            continue
        result.builds_recorded += 1
        result.samples_written += written

    if result.builds_recorded:
        logger.info(
            "Recorded usage for %s build(s), %s sample(s)",
            result.builds_recorded,
            result.samples_written,
        )
    return result
