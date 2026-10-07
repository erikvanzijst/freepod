"""The sampling loop: where it resumes, how far it goes, and what it refuses."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlmodel import select

from app.config import CaelusSettings, get_settings
from app.models import (
    ProductORM,
    ProductTemplateVersionORM,
    UsageSampleORM,
    UsageSubjectORM,
    UserORM,
)
from app.services.usage import sampler
from app.services.usage.buckets import BucketSizeSource
from app.services.usage.containers import OpenCostSource
from app.services.usage.databases import DatabaseSizeSource
from app.services.usage.opencost import OpenCostClient
from app.services.usage.sampler import (
    align,
    last_recorded_window,
    pending_windows,
    recordable_until,
    resume_from,
    sample_once,
)
from tests.conftest import make_deployment_with_release
from tests.usage_fixtures import seeded_catalog  # noqa: F401

FIXTURES = Path(__file__).parent / "fixtures"
HOUR = 3600
COVERED = {"data": {"result": [{"metric": {}, "value": [1790161200, "126"]}]}}
UNCOVERED: dict = {"data": {"result": []}}


@pytest.fixture
def settings() -> CaelusSettings:
    return CaelusSettings(
        **{
            **get_settings().model_dump(),
            "usage_window_seconds": HOUR,
            "usage_settle_seconds": 300,
            "usage_first_run_lookback_seconds": 6 * HOUR,
            "usage_max_windows_per_pass": 24,
        }
    )


def _body(window_start: datetime) -> str:
    """The recorded fixture, restamped onto the window being asked for."""
    payload = json.loads((FIXTURES / "opencost_allocation.json").read_text())
    window = payload["data"][0]
    end = window_start + timedelta(seconds=HOUR)
    stamp = lambda m: m.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    for entry in window.values():
        entry["window"] = {"start": stamp(window_start), "end": stamp(end)}
        entry["start"], entry["end"] = stamp(window_start), stamp(end)
    return json.dumps({"code": 200, "data": [window]})


def _client(*, cover=True, fail_after=None) -> OpenCostClient:
    """Answers every window from the fixture; optionally refuses after N fetches."""
    state = {"fetches": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "/api/v1/query" in request.url.path:
            return httpx.Response(200, json=COVERED if cover else UNCOVERED)
        state["fetches"] += 1
        if fail_after is not None and state["fetches"] > fail_after:
            return httpx.Response(503)
        window = request.url.params["window"].split(",")[0]
        start = datetime.strptime(window, "%Y-%m-%dT%H:%M:%SZ")
        return httpx.Response(
            200,
            content=_body(start),
            headers={"content-type": "application/json"},
        )

    return OpenCostClient(
        "http://opencost:9003",
        prometheus_url="http://prometheus",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


@pytest.fixture
def tenants(db_session):
    """The two namespaces the fixture's allocations belong to."""
    user = UserORM(email="owner@example.com")
    product = ProductORM(name="bookstack")
    db_session.add(user)
    db_session.add(product)
    db_session.commit()
    template = ProductTemplateVersionORM(
        product_id=product.id,
        chart_ref="oci://example/bookstack",
        chart_version="1.0.0",
        values_schema_json={},
    )
    db_session.add(template)
    db_session.commit()
    deployment = make_deployment_with_release(
        db_session,
        user_id=user.id,
        desired_template_id=template.id,
        name="books",
        namespace="bookstack-fred-mi4dpvrph",
    )
    db_session.commit()
    return deployment


# resume position


def test_an_empty_ledger_falls_back_to_a_bounded_lookback(db_session):
    now = datetime(2026, 9, 23, 14, 30)
    start = resume_from(
        db_session, now=now, window_seconds=HOUR, lookback_seconds=6 * HOUR
    )
    assert start == datetime(2026, 9, 23, 8)
    assert last_recorded_window(db_session) is None


def test_the_lookback_is_bounded_not_the_whole_retention(db_session):
    """One enormous first request is how a first run fails."""
    now = datetime(2026, 9, 23, 14, 30)
    start = resume_from(
        db_session, now=now, window_seconds=HOUR, lookback_seconds=6 * HOUR
    )
    assert now - start < timedelta(days=1)


def test_a_current_ledger_resumes_one_window_past_it(
    db_session, seeded_catalog, tenants
):
    recorded = datetime(2026, 9, 23, 13)
    _seed_sample(db_session, recorded)
    start = resume_from(
        db_session,
        now=datetime(2026, 9, 23, 14, 30),
        window_seconds=HOUR,
        lookback_seconds=6 * HOUR,
    )
    assert start == datetime(2026, 9, 23, 14)


def test_a_ledger_that_has_fallen_behind_resumes_from_the_gap(
    db_session, seeded_catalog, tenants
):
    """Not from the lookback: the gap is what has to be replayed."""
    _seed_sample(db_session, datetime(2026, 9, 21, 3))
    start = resume_from(
        db_session,
        now=datetime(2026, 9, 23, 14, 30),
        window_seconds=HOUR,
        lookback_seconds=6 * HOUR,
    )
    assert start == datetime(2026, 9, 21, 4)


def test_the_position_is_the_ledger_itself(db_session, seeded_catalog, tenants):
    """A crash cannot desynchronize it, because there is nothing else to sync."""
    _seed_sample(db_session, datetime(2026, 9, 23, 11))
    assert last_recorded_window(db_session) == datetime(2026, 9, 23, 11)


def test_another_writers_samples_do_not_advance_the_position(
    db_session, seeded_catalog, tenants
):
    """A build recorded for 13:00 while the sampler is stuck at 10:00 -- say
    OpenCost is down -- must not make it skip 11:00 and 12:00."""
    _seed_sample(db_session, datetime(2026, 9, 23, 10))
    _seed_sample(db_session, datetime(2026, 9, 23, 13), kind="build")

    assert last_recorded_window(db_session) == datetime(2026, 9, 23, 10)


def test_only_another_writers_samples_is_an_empty_position(db_session, seeded_catalog):
    _seed_sample(db_session, datetime(2026, 9, 23, 13), kind="build")

    assert last_recorded_window(db_session) is None


def test_the_own_builds_namespace_is_not_sampled(
    db_session, seeded_catalog, tenants, settings
):
    """`caelus-dev` stands in for the builds namespace: the fixture has no build pods."""
    own = settings.model_copy(update={"builds_namespace": "caelus-dev"})
    sample_once(db_session, _client(), now=datetime(2026, 9, 23, 14, 30), settings=own)

    namespaces = {s.namespace for s in db_session.exec(select(UsageSubjectORM)).all()}
    assert "caelus-dev" not in namespaces
    assert "bookstack-fred-mi4dpvrph" in namespaces


def test_another_environments_builds_namespace_is_sampled(
    db_session, seeded_catalog, tenants, settings
):
    other = settings.model_copy(update={"builds_namespace": "caelus-builds"})
    sample_once(db_session, _client(), now=datetime(2026, 9, 23, 14, 30), settings=other)

    subjects = db_session.exec(
        select(UsageSubjectORM).where(UsageSubjectORM.namespace == "caelus-dev")
    ).all()
    assert subjects and all(s.deployment_id is None for s in subjects)


# recordable range


def test_a_run_at_1430_stops_after_the_1300_window():
    end = recordable_until(
        now=datetime(2026, 9, 23, 14, 30), window_seconds=HOUR, settle_seconds=300
    )
    assert end == datetime(2026, 9, 23, 14)


def test_the_in_progress_window_is_never_recordable(db_session):
    windows = pending_windows(
        db_session,
        now=datetime(2026, 9, 23, 14, 30),
        window_seconds=HOUR,
        settle_seconds=300,
        lookback_seconds=6 * HOUR,
        max_windows=24,
    )
    assert datetime(2026, 9, 23, 14) not in windows
    assert max(windows) == datetime(2026, 9, 23, 13)


def test_a_window_is_not_read_until_the_settling_allowance_has_passed():
    """A run one minute after the hour closes must still wait."""
    end = recordable_until(
        now=datetime(2026, 9, 23, 14, 1), window_seconds=HOUR, settle_seconds=300
    )
    assert end == datetime(2026, 9, 23, 13)


def test_window_starts_are_aligned_to_the_window_length():
    assert align(datetime(2026, 9, 23, 14, 37, 12), HOUR) == datetime(2026, 9, 23, 14)


def test_the_grid_does_not_drift_over_a_long_run():
    """Every start stays anchored to the epoch grid; the steps are exact."""
    cursor = align(datetime(2026, 1, 1), HOUR)
    for _ in range(24 * 366):
        cursor += timedelta(seconds=HOUR)
    assert (cursor - datetime(1970, 1, 1)).total_seconds() % HOUR == 0
    assert align(cursor, HOUR) == cursor


@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 9, 23, 14, 37, 12, 456789),
        datetime(2026, 10, 25, 2, 59, 59, 999999),
        datetime(2026, 3, 29, 1, 0, 0, 1),
        datetime(2028, 2, 29, 0, 0, 1),
        datetime(2027, 1, 1, 0, 0, 0),
    ],
)
def test_every_window_starts_on_the_hour_whatever_the_clock_reads(db_session, now):
    windows = pending_windows(
        db_session,
        now=now,
        window_seconds=HOUR,
        settle_seconds=300,
        lookback_seconds=6 * HOUR,
        max_windows=24,
    )
    assert windows
    assert all((w.minute, w.second, w.microsecond) == (0, 0, 0) for w in windows)


def test_daylight_saving_transitions_are_not_a_special_case(db_session):
    """These are naive UTC, so a local clock change is not a discontinuity here."""
    for moment in (datetime(2026, 3, 29, 1, 30), datetime(2026, 10, 25, 1, 30)):
        windows = pending_windows(
            db_session,
            now=moment,
            window_seconds=HOUR,
            settle_seconds=300,
            lookback_seconds=6 * HOUR,
            max_windows=24,
        )
        gaps = {(b - a).total_seconds() for a, b in zip(windows, windows[1:])}
        assert gaps == {float(HOUR)}


# gap replay


def test_a_day_long_gap_is_replayed_hour_by_hour(db_session, seeded_catalog, tenants):
    _seed_sample(db_session, datetime(2026, 9, 22, 13))
    windows = pending_windows(
        db_session,
        now=datetime(2026, 9, 23, 14, 30),
        window_seconds=HOUR,
        settle_seconds=300,
        lookback_seconds=6 * HOUR,
        max_windows=24,
    )
    assert len(windows) == 24
    assert windows[0] == datetime(2026, 9, 22, 14)
    assert all(
        b - a == timedelta(seconds=HOUR) for a, b in zip(windows, windows[1:])
    )


def test_a_pass_is_bounded_so_recovery_is_incremental(
    db_session, seeded_catalog, tenants
):
    _seed_sample(db_session, datetime(2026, 9, 20, 0))
    windows = pending_windows(
        db_session,
        now=datetime(2026, 9, 23, 14, 30),
        window_seconds=HOUR,
        settle_seconds=300,
        lookback_seconds=6 * HOUR,
        max_windows=6,
    )
    assert len(windows) == 6


def test_progress_is_kept_when_a_catch_up_is_interrupted(
    db_session, seeded_catalog, tenants, settings
):
    """The windows already recorded survive; the next pass continues from there."""
    now = datetime(2026, 9, 23, 14, 30)
    run = sample_once(
        db_session, _client(fail_after=2), now=now, settings=settings
    )
    assert run.windows_recorded == 2
    assert run.windows_skipped == 1
    assert last_recorded_window(db_session) == datetime(2026, 9, 23, 9)

    resumed = resume_from(
        db_session, now=now, window_seconds=HOUR, lookback_seconds=6 * HOUR
    )
    assert resumed == datetime(2026, 9, 23, 10)


def test_a_full_pass_records_every_eligible_window(
    db_session, seeded_catalog, tenants, settings
):
    run = sample_once(
        db_session, _client(), now=datetime(2026, 9, 23, 14, 30), settings=settings
    )
    assert run.windows_recorded == 6
    assert run.samples_written > 0
    recorded = {
        s.window_start for s in db_session.exec(select(UsageSampleORM)).all()
    }
    assert recorded == {datetime(2026, 9, 23, h) for h in range(8, 14)}


# unusable windows


def test_an_untrustworthy_window_writes_nothing_and_moves_nothing(
    db_session, seeded_catalog, tenants, settings
):
    """Closes task 2.3: the position must not pass a window it could not measure."""
    before = last_recorded_window(db_session)
    run = sample_once(
        db_session,
        _client(cover=False),
        now=datetime(2026, 9, 23, 14, 30),
        settings=settings,
    )
    assert run.windows_recorded == 0
    assert run.samples_written == 0
    assert not db_session.exec(select(UsageSampleORM)).all()
    assert last_recorded_window(db_session) == before


def test_an_unreachable_source_writes_nothing_and_moves_nothing(
    db_session, seeded_catalog, tenants, settings
):
    run = sample_once(
        db_session,
        _client(fail_after=0),
        now=datetime(2026, 9, 23, 14, 30),
        settings=settings,
    )
    assert run.windows_recorded == 0
    assert not db_session.exec(select(UsageSampleORM)).all()
    assert last_recorded_window(db_session) is None


def test_a_gap_is_not_recorded_past(db_session, seeded_catalog, tenants, settings):
    """Recording past an unmeasurable window would strand the position permanently."""
    run = sample_once(
        db_session, _client(fail_after=1), now=datetime(2026, 9, 23, 14, 30),
        settings=settings,
    )
    assert run.windows_recorded == 1
    recorded = {s.window_start for s in db_session.exec(select(UsageSampleORM)).all()}
    assert recorded == {datetime(2026, 9, 23, 8)}


# concurrency


def test_two_simultaneous_runs_leave_one_sample_per_series(
    db_session, seeded_catalog, tenants, settings
):
    now = datetime(2026, 9, 23, 14, 30)
    first = sample_once(db_session, _client(), now=now, settings=settings)
    assert first.windows_recorded == 6

    for window_start in (datetime(2026, 9, 23, h) for h in range(8, 14)):
        sampler.record_window(
            db_session,
            _client(),
            window_start,
            window_seconds=HOUR,
            observed_at=now,
            environment="dev",
        )
    db_session.commit()

    rows = db_session.exec(select(UsageSampleORM)).all()
    keys = {(r.subject_id, r.metric_id, r.window_start) for r in rows}
    assert len(rows) == len(keys), "one sample per subject, quantity and window"


def test_two_concurrent_sessions_leave_one_sample_per_series(
    db_session, seeded_catalog, tenants, settings, test_database
):
    """Two separate connections, both recording the same window.

    The natural primary key is the arbiter -- nothing is claimed or leased -- so this
    exercises the real conflict path rather than a sequential replay.
    """
    from sqlmodel import Session

    now = datetime(2026, 9, 23, 14, 30)
    window_start = datetime(2026, 9, 23, 8)

    # Interleaving them uncommitted would just block: the upsert takes a row lock, so
    # concurrent samplers serialize rather than race. The committed conflict is the
    # one worth testing.
    sampler.record_window(
        db_session, _client(), window_start, window_seconds=HOUR, observed_at=now,
        environment="dev",
    )
    db_session.commit()

    with Session(test_database.engine) as other:
        sampler.record_window(
            other, _client(), window_start, window_seconds=HOUR, observed_at=now,
            environment="dev",
        )
        other.commit()

    rows = db_session.exec(select(UsageSampleORM)).all()
    keys = {(r.subject_id, r.metric_id, r.window_start) for r in rows}
    assert rows
    assert len(rows) == len(keys), "one sample per subject, quantity and window"
    subjects = db_session.exec(select(UsageSubjectORM)).all()
    assert len({s.ref for s in subjects}) == len(subjects), "and one row per subject"


def test_a_replayed_window_is_left_unchanged(
    db_session, seeded_catalog, tenants, settings
):
    now = datetime(2026, 9, 23, 14, 30)
    sample_once(db_session, _client(), now=now, settings=settings)
    before = {
        (r.subject_id, r.metric_id, r.window_start): (r.value, r.observed_at)
        for r in db_session.exec(select(UsageSampleORM)).all()
    }

    sampler.record_window(
        db_session,
        _client(),
        datetime(2026, 9, 23, 8),
        window_seconds=HOUR,
        observed_at=datetime(2026, 9, 24, 9),
        environment="dev",
    )
    db_session.commit()

    after = {
        (r.subject_id, r.metric_id, r.window_start): (r.value, r.observed_at)
        for r in db_session.exec(select(UsageSampleORM)).all()
    }
    assert after == before


# A metric each kind's writer records: the sampler's position is one of the first, and a
# build records the second, as it does every container quantity but three.
_SEED_METRIC = {"container": "network_receive_bytes", "build": "cpu_core_hours"}


def _seed_sample(session, window_start: datetime, *, kind: str = "container") -> None:
    """One recorded sample, which is all the cursor reads."""
    from app.models import UsageMetricORM

    subject = UsageSubjectORM(kind=kind, ref=f"ns/d/c/{window_start:%H}/{kind}", namespace="ns")
    session.add(subject)
    session.commit()
    session.refresh(subject)
    metric = session.exec(
        select(UsageMetricORM).where(UsageMetricORM.name == _SEED_METRIC[kind])
    ).one()
    session.add(
        UsageSampleORM(
            subject_id=subject.id,
            metric_id=metric.id,
            window_start=window_start,
            interval_seconds=HOUR,
            observed_at=window_start,
            value=Decimal("1"),
        )
    )
    session.commit()


# position metrics


def _sources_position_metrics() -> dict[str, frozenset[str]]:
    return {
        source.name: source.position_metrics
        for source in (OpenCostSource, DatabaseSizeSource, BucketSizeSource)
    }


def _build_quantities() -> set[str]:
    """Every quantity a build records, measured or estimated."""
    from uuid import uuid4

    from app.models import BuildORM
    from app.services.build_constants import BUILD_STATUS_SUCCEEDED
    from app.services.usage.builds import window_quantities

    start, end = datetime(2026, 9, 25, 14, 10), datetime(2026, 9, 25, 14, 20)
    estimated = dict(
        artifact_id=uuid4().hex,
        deployment_id=uuid4(),
        status=BUILD_STATUS_SUCCEEDED,
        job_id="build-x",
        started_at=start,
        finished_at=end,
    )
    measured = estimated | dict(
        usage_cpu_seconds=10.0,
        usage_memory_byte_seconds=60 * 2**29,
        usage_memory_peak_bytes=2**30,
        usage_started_at=start,
        usage_finished_at=end,
    )
    return {
        metric
        for fields in (estimated, measured)
        for window in window_quantities(BuildORM(**fields), window_seconds=HOUR)
        for metric in window.quantities
    }


def test_position_metrics_are_exclusive_to_their_source():
    """A metric two writers record would let one advance the other's position."""
    sets = _sources_position_metrics()
    names = sorted(sets)
    for i, a in enumerate(names):
        assert sets[a], f"{a} has no position metric"
        for b in names[i + 1 :]:
            assert not sets[a] & sets[b], f"{a} and {b} share position metrics"

    builds = _build_quantities()
    assert builds, "builds record nothing; the check below would be vacuous"
    for name, metrics in sets.items():
        assert not metrics & builds, f"builds record {name}'s {sorted(metrics & builds)}"


def _seed_ledger(session, *, metrics: list[str], hours: range, subjects: int) -> None:
    """Many samples cheaply: every subject, metric and hour."""
    from sqlalchemy import text

    session.execute(
        text(
            "INSERT INTO usage_subject (kind, ref, first_seen_at, last_seen_at) "
            "SELECT 'container', 'seed-' || g, now(), now() "
            "FROM generate_series(1, :n) g ON CONFLICT DO NOTHING"
        ),
        {"n": subjects},
    )
    session.execute(
        text(
            "INSERT INTO usage_sample "
            "(subject_id, metric_id, window_start, interval_seconds, observed_at, value) "
            "SELECT s.id, m.id, CAST(:base AS timestamp) + h * interval '1 hour', 3600, now(), 1 "
            "FROM usage_subject s, usage_metric m, generate_series(CAST(:first AS int), CAST(:last AS int)) h "
            "WHERE s.ref LIKE 'seed-%' AND m.name = ANY(:metrics)"
        ),
        {"base": datetime(2026, 9, 1), "first": hours.start, "last": hours.stop - 1, "metrics": metrics},
    )
    session.execute(text("ANALYZE usage_sample"))
    session.commit()


def _rows_read(session, metric: str) -> tuple[set[str], int]:
    """The indexes the position lookup used, and the sample rows it read."""
    import json as _json

    from sqlalchemy import text
    from sqlalchemy.dialects import postgresql

    from app.models import UsageMetricORM

    metric_id = session.exec(
        select(UsageMetricORM.id).where(UsageMetricORM.name == metric)
    ).one()
    sql = sampler.position_of(metric_id).compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    )
    (plan,) = session.execute(text(f"EXPLAIN (ANALYZE, FORMAT JSON) {sql}")).scalar_one()
    if isinstance(plan, str):
        plan = _json.loads(plan)[0]

    indexes: set[str] = set()
    read = 0

    def walk(node: dict) -> None:
        nonlocal read
        if node.get("Relation Name") == "usage_sample":
            indexes.add(node.get("Index Name", node["Node Type"]))
            read += node["Actual Rows"] + node.get("Rows Removed by Filter", 0)
        for child in node.get("Plans", []):
            walk(child)

    walk(plan["Plan"])
    return indexes, read


def test_a_source_with_no_samples_reads_none_of_the_others(db_session, seeded_catalog):
    """The ledger holds other sources' samples only; finding nothing reads nothing."""
    _seed_ledger(
        db_session,
        metrics=["cpu_core_hours", "ram_byte_hours", "network_receive_bytes"],
        hours=range(0, 48),
        subjects=200,
    )

    for metric in DatabaseSizeSource.position_metrics:
        indexes, read = _rows_read(db_session, metric)
        assert indexes == {"ix_usage_sample_metric_window"}
        assert read == 0


def test_a_lagging_source_reads_one_row_however_far_behind(db_session, seeded_catalog):
    """Containers stopped at hour 9 while builds' and databases' samples carried on:
    the position is still one index descent, not a walk back through the newer rows."""
    _seed_ledger(db_session, metrics=sorted(OpenCostSource.position_metrics), hours=range(0, 10), subjects=200)
    _seed_ledger(
        db_session, metrics=["cpu_core_hours", "db_byte_hours"], hours=range(0, 200), subjects=200
    )

    assert last_recorded_window(db_session) == datetime(2026, 9, 1, 9)
    for metric in OpenCostSource.position_metrics:
        indexes, read = _rows_read(db_session, metric)
        assert indexes == {"ix_usage_sample_metric_window"}
        assert read == 1
