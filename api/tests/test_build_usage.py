"""A build's usage in the ledger: the per-window arithmetic, and the recording pass."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlmodel import Session, select

from app.config import CaelusSettings
from app.models import BuildORM, UsageMetricORM, UsageSampleORM, UsageSubjectORM
from app.models.usage import SubjectKind
from app.services import build_jobs
from app.services.build_constants import (
    BUILD_STATUS_CANCELED,
    BUILD_STATUS_FAILED,
    BUILD_STATUS_RUNNING,
    BUILD_STATUS_SUCCEEDED,
)
from app.services.usage import builds as build_usage
from app.services.usage.builds import (
    CPU_REQUEST_CORES,
    MEMORY_REQUEST_BYTES,
    record_settled_builds,
    window_quantities,
)
from tests.conftest import db_session, make_accepted_user, make_bare_deployment  # noqa: F401
from tests.usage_fixtures import GIB, seeded_catalog  # noqa: F401

HOUR = 3600
T14 = datetime(2026, 9, 25, 14)
USAGE_AVERAGES = {"cpu_usage_cores_avg", "ram_usage_bytes_avg"}
EPSILON = Decimal("1e-20")


def _hours(seconds: int) -> Decimal:
    return Decimal(seconds) / HOUR


def _build(
    *,
    start: datetime,
    end: datetime,
    cpu_seconds: float | None = 10.0,
    memory_byte_seconds: int | None = 60 * 2**29,
    measured: bool = True,
    worker_delay: timedelta = timedelta(seconds=5),
    **kwargs,
) -> BuildORM:
    """A finished build whose container ran from `start` to `end`.

    The worker's own times trail the container's by `worker_delay`, as its
    polling makes them do.
    """
    fields = dict(
        artifact_id=uuid4().hex,
        deployment_id=uuid4(),
        status=BUILD_STATUS_SUCCEEDED,
        job_id="build-x",
        started_at=start + worker_delay,
        finished_at=end + worker_delay,
    )
    if measured:
        fields |= dict(
            usage_cpu_seconds=cpu_seconds,
            usage_memory_byte_seconds=memory_byte_seconds,
            usage_memory_peak_bytes=2**30,
            usage_started_at=start,
            usage_finished_at=end,
        )
    return BuildORM(**(fields | kwargs))


# ---------------------------------------------------------------------------
# Per-window quantities
# ---------------------------------------------------------------------------


def test_the_request_constants_are_the_jobs():
    assert (build_jobs.CPU_REQUEST, CPU_REQUEST_CORES) == ("500m", Decimal("0.5"))
    assert (build_jobs.MEMORY_REQUEST, MEMORY_REQUEST_BYTES) == ("1Gi", GIB)
    assert build_usage.CPU_LIMIT_CORES == 2
    assert build_usage.MEMORY_LIMIT_BYTES == 6 * GIB


def test_a_build_within_one_hour_lands_in_that_window():
    build = _build(start=T14 + timedelta(minutes=10), end=T14 + timedelta(minutes=12))

    (window,) = window_quantities(build, window_seconds=HOUR)

    assert window.window_start == T14
    assert window.quantities["running_seconds"] == 120


def test_the_run_is_the_containers_own_not_the_workers():
    """The worker's times trail by its polling; with a 55 s delay they would
    cross into the next hour."""
    build = _build(
        start=T14 + timedelta(minutes=58),
        end=T14 + timedelta(minutes=59),
        worker_delay=timedelta(seconds=90),
    )

    assert [w.window_start for w in window_quantities(build, window_seconds=HOUR)] == [T14]


def test_a_build_across_an_hour_boundary_is_split_by_its_run():
    build = _build(
        start=T14 + timedelta(minutes=59),
        end=T14 + timedelta(minutes=61),
        cpu_seconds=400.0,
        memory_byte_seconds=120 * 4 * 2**30,
    )

    first, second = window_quantities(build, window_seconds=HOUR)

    assert (first.window_start, second.window_start) == (T14, T14 + timedelta(hours=1))
    for metric in ("cpu_core_hours", "ram_byte_hours", "running_seconds"):
        assert first.quantities[metric] == second.quantities[metric]
    total_cpu = first.quantities["cpu_core_hours"] + second.quantities["cpu_core_hours"]
    assert abs(total_cpu - Decimal(400) / HOUR) < EPSILON
    total_ram = first.quantities["ram_byte_hours"] + second.quantities["ram_byte_hours"]
    assert abs(total_ram - Decimal(120 * 4 * 2**30) / HOUR) < EPSILON


def test_an_uneven_split_follows_the_share_of_the_run():
    build = _build(
        start=T14 + timedelta(minutes=59),
        end=T14 + timedelta(minutes=62),
        cpu_seconds=900.0,
    )

    first, second = window_quantities(build, window_seconds=HOUR)

    assert first.quantities["running_seconds"] == 60
    assert second.quantities["running_seconds"] == 120
    assert abs(first.quantities["cpu_core_hours"] - Decimal(300) / HOUR) < EPSILON
    assert abs(second.quantities["cpu_core_hours"] - Decimal(600) / HOUR) < EPSILON


def test_a_light_build_is_billed_at_its_requests():
    build = _build(
        start=T14,
        end=T14 + timedelta(minutes=2),
        cpu_seconds=10.0,  # 0.083 cores against 0.5 requested
        memory_byte_seconds=120 * 2**28,  # 256 MiB against 1 GiB requested
    )

    (window,) = window_quantities(build, window_seconds=HOUR)

    assert window.quantities["cpu_core_hours"] == CPU_REQUEST_CORES * _hours(120)
    assert window.quantities["ram_byte_hours"] == MEMORY_REQUEST_BYTES * _hours(120)


def test_a_heavy_build_is_billed_at_what_it_used():
    build = _build(
        start=T14,
        end=T14 + timedelta(minutes=2),
        cpu_seconds=180.0,  # 1.5 cores
        memory_byte_seconds=120 * 3 * 2**30,  # 3 GiB
    )

    (window,) = window_quantities(build, window_seconds=HOUR)

    assert window.quantities["cpu_core_hours"] == Decimal(180) / HOUR
    assert window.quantities["ram_byte_hours"] == Decimal(120 * 3 * 2**30) / HOUR


def test_usage_and_allowances_are_recorded_side_by_side():
    build = _build(
        start=T14, end=T14 + timedelta(minutes=2), cpu_seconds=60.0,
        memory_byte_seconds=120 * 2**29,
    )

    (window,) = window_quantities(build, window_seconds=HOUR)

    assert window.quantities["cpu_usage_cores_avg"] == Decimal("0.5")
    assert window.quantities["ram_usage_bytes_avg"] == Decimal(2**29)
    assert window.quantities["cpu_request_cores_avg"] == Decimal("0.5")
    assert window.quantities["cpu_limit_cores_avg"] == 2
    assert window.quantities["ram_request_bytes_avg"] == GIB
    assert window.quantities["ram_limit_bytes_avg"] == 6 * GIB


def test_averages_are_over_the_run_in_every_window():
    """As OpenCost reports every container's, and so every row in the ledger."""
    build = _build(
        start=T14 + timedelta(minutes=59), end=T14 + timedelta(minutes=62), cpu_seconds=90.0
    )

    first, second = window_quantities(build, window_seconds=HOUR)

    assert first.quantities["cpu_usage_cores_avg"] == Decimal("0.5")
    assert second.quantities["cpu_usage_cores_avg"] == Decimal("0.5")


def test_an_estimated_build_records_its_requests_over_the_workers_times():
    build = _build(
        start=T14 + timedelta(minutes=10),
        end=T14 + timedelta(minutes=12),
        measured=False,
        worker_delay=timedelta(seconds=30),
    )

    (window,) = window_quantities(build, window_seconds=HOUR)

    assert window.quantities["running_seconds"] == 120
    assert window.quantities["cpu_core_hours"] == CPU_REQUEST_CORES * _hours(120)
    assert window.quantities["ram_byte_hours"] == MEMORY_REQUEST_BYTES * _hours(120)
    assert window.quantities["cpu_request_cores_avg"] == CPU_REQUEST_CORES
    assert not USAGE_AVERAGES & window.quantities.keys()


def test_a_build_with_no_run_records_nothing():
    build = _build(start=T14, end=T14, measured=False)

    assert window_quantities(build, window_seconds=HOUR) == []


# ---------------------------------------------------------------------------
# The recording pass
# ---------------------------------------------------------------------------


@pytest.fixture
def settings():
    return CaelusSettings(_env_file=None, builds_namespace="caelus-builds-test")


@pytest.fixture
def deployment(db_session, seeded_catalog):
    user = make_accepted_user(db_session, "builder@example.com")
    return make_bare_deployment(db_session, user.id)


def _stored(db_session, deployment, **kwargs) -> BuildORM:
    kwargs.setdefault("start", T14 + timedelta(minutes=8))
    kwargs.setdefault("end", T14 + timedelta(minutes=10))
    build = _build(**kwargs)
    build.deployment_id = deployment.id
    db_session.add(build)
    db_session.commit()
    db_session.refresh(build)
    return build


def _samples(db_session, build: BuildORM) -> dict[tuple[datetime, str], Decimal]:
    rows = db_session.exec(
        select(UsageSampleORM.window_start, UsageMetricORM.name, UsageSampleORM.value)
        .join(UsageMetricORM, UsageMetricORM.id == UsageSampleORM.metric_id)
        .join(UsageSubjectORM, UsageSubjectORM.id == UsageSampleORM.subject_id)
        .where(UsageSubjectORM.kind == SubjectKind.BUILD, UsageSubjectORM.ref == str(build.id))
    ).all()
    return {(start, name): value for start, name, value in rows}


def test_nothing_is_recorded_before_the_window_settles(db_session, settings, deployment):
    build = _stored(db_session, deployment)

    result = record_settled_builds(
        db_session, now=T14 + timedelta(hours=1, minutes=4), settings=settings
    )

    db_session.refresh(build)
    assert result.builds_recorded == 0
    assert build.usage_recorded_at is None
    assert _samples(db_session, build) == {}


def test_a_settled_build_is_recorded_once(db_session, settings, deployment):
    build = _stored(db_session, deployment)
    now = T14 + timedelta(hours=1, minutes=5)

    first = record_settled_builds(db_session, now=now, settings=settings)
    second = record_settled_builds(db_session, now=now + timedelta(hours=1), settings=settings)

    db_session.refresh(build)
    assert (first.builds_recorded, second.builds_recorded) == (1, 0)
    assert build.usage_recorded_at == now
    samples = _samples(db_session, build)
    assert first.samples_written == len(samples) == 9
    assert samples[(T14, "cpu_core_hours")] == CPU_REQUEST_CORES * _hours(120)


def test_the_subject_is_the_build_attributed_to_its_deployment(db_session, settings, deployment):
    build = _stored(db_session, deployment)

    record_settled_builds(db_session, now=T14 + timedelta(hours=2), settings=settings)

    subject = db_session.exec(select(UsageSubjectORM)).one()
    assert subject.kind == SubjectKind.BUILD
    assert subject.ref == str(build.id)
    assert subject.namespace == "caelus-builds-test"
    assert subject.deployment_id == deployment.id


def test_a_failed_build_is_recorded_too(db_session, settings, deployment):
    build = _stored(db_session, deployment, status=BUILD_STATUS_FAILED)

    record_settled_builds(db_session, now=T14 + timedelta(hours=2), settings=settings)

    assert _samples(db_session, build)


def test_builds_with_no_job_or_not_finished_are_not_recorded(db_session, settings, deployment):
    no_job = _stored(db_session, deployment, status=BUILD_STATUS_FAILED, job_id=None)
    running = _stored(db_session, deployment, status=BUILD_STATUS_RUNNING)
    canceled = _stored(db_session, deployment, status=BUILD_STATUS_CANCELED)

    result = record_settled_builds(db_session, now=T14 + timedelta(hours=2), settings=settings)

    assert result.builds_recorded == 0
    for build in (no_job, running, canceled):
        db_session.refresh(build)
        assert build.usage_recorded_at is None


def test_a_build_already_marked_is_never_recorded(db_session, settings, deployment):
    """As every build finished before recording existed is, by the migration."""
    build = _stored(db_session, deployment, usage_recorded_at=T14)

    result = record_settled_builds(db_session, now=T14 + timedelta(hours=2), settings=settings)

    assert result.builds_recorded == 0
    assert _samples(db_session, build) == {}


def test_a_build_spanning_two_windows_waits_for_the_second(db_session, settings, deployment):
    build = _stored(
        db_session,
        deployment,
        start=T14 + timedelta(minutes=59),
        end=T14 + timedelta(minutes=61),
    )

    early = record_settled_builds(db_session, now=T14 + timedelta(hours=1, minutes=30), settings=settings)
    late = record_settled_builds(db_session, now=T14 + timedelta(hours=2, minutes=5), settings=settings)

    assert (early.builds_recorded, late.builds_recorded) == (0, 1)
    assert {start for start, _ in _samples(db_session, build)} == {T14, T14 + timedelta(hours=1)}


def test_a_crash_mid_record_leaves_nothing_and_a_later_pass_records_in_full(
    db_session, settings, deployment, monkeypatch
):
    build = _stored(db_session, deployment)
    real = build_usage.ledger.record_samples

    def crash_after_writing(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("worker killed")

    monkeypatch.setattr(build_usage.ledger, "record_samples", crash_after_writing)
    crashed = record_settled_builds(db_session, now=T14 + timedelta(hours=2), settings=settings)

    db_session.refresh(build)
    assert crashed.failed == [build.id]
    assert build.usage_recorded_at is None
    assert _samples(db_session, build) == {}

    monkeypatch.setattr(build_usage.ledger, "record_samples", real)
    recovered = record_settled_builds(db_session, now=T14 + timedelta(hours=2), settings=settings)

    assert recovered.builds_recorded == 1
    assert len(_samples(db_session, build)) == 9


def test_one_failing_build_does_not_hold_up_the_others(
    db_session, settings, deployment, monkeypatch
):
    bad = _stored(db_session, deployment)
    good = _stored(db_session, deployment, start=T14 + timedelta(minutes=20), end=T14 + timedelta(minutes=21))
    real = build_usage.record_build

    def fail_one(session, build, **kwargs):
        if build.id == bad.id:
            raise RuntimeError("bad row")
        return real(session, build, **kwargs)

    monkeypatch.setattr(build_usage, "record_build", fail_one)
    result = record_settled_builds(db_session, now=T14 + timedelta(hours=2), settings=settings)

    assert result.failed == [bad.id]
    assert result.builds_recorded == 1
    assert _samples(db_session, good)


def test_two_racing_passes_record_a_build_once(db_session, settings, deployment):
    build = _stored(db_session, deployment)
    now = T14 + timedelta(hours=2)

    with Session(db_session.get_bind()) as other:
        # The other pass has the build locked, mid-record.
        held = build_usage._next_pending(
            other, settled_before=T14 + timedelta(hours=1), exclude=[]
        )
        assert held.id == build.id

        skipped = record_settled_builds(db_session, now=now, settings=settings)
        assert skipped.builds_recorded == 0 and not skipped.failed

        build_usage.record_build(
            other, held, now=now, settings=settings,
            catalog=build_usage.ledger.metric_ids(other),
        )
        other.commit()

    after = record_settled_builds(db_session, now=now, settings=settings)

    assert after.builds_recorded == 0
    assert len(_samples(db_session, build)) == 9


def test_recording_a_build_twice_writes_its_samples_once(db_session, settings, deployment):
    """The insert is idempotent, so even two passes that both got the row agree."""
    build = _stored(db_session, deployment)
    catalog = build_usage.ledger.metric_ids(db_session)
    now = T14 + timedelta(hours=2)

    first = build_usage.record_build(db_session, build, now=now, settings=settings, catalog=catalog)
    second = build_usage.record_build(db_session, build, now=now, settings=settings, catalog=catalog)
    db_session.commit()

    assert (first, second) == (9, 0)
    assert len(db_session.exec(select(UsageSubjectORM)).all()) == 1
