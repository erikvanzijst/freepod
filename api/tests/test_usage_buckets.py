"""The object storage source: which buckets are recorded, for which windows, and as whom."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import event
from sqlmodel import select

from app.config import CaelusSettings, get_settings
from app.models import UsageMetricORM, UsageSampleORM, UsageSubjectORM
from app.services.usage import sampler
from app.services.usage.buckets import BucketSizeSource, deployment_id_of
from app.services.usage.containers import OpenCostSource
from app.services.usage.prometheus import PrometheusClient
from app.services.usage.sampler import last_recorded_window, record_source_window, sample_once
from tests.conftest import make_accepted_user, make_bare_deployment
from tests.test_usage_databases import FakePrometheus as FakeDatabasePrometheus
from tests.test_usage_databases import _deployment_with_database
from tests.test_usage_sampler import _client as opencost_client
from tests.test_usage_sampler import tenants  # noqa: F401
from tests.usage_fixtures import seeded_catalog  # noqa: F401

HOUR = 3600
GIB = 2**30
NAMESPACE = "caelus-garage-dev"
NOW = datetime(2026, 10, 7, 14, 30)
WINDOW = datetime(2026, 10, 7, 13)
POSITION = BucketSizeSource.position_metrics


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


class FakePrometheus:
    """Answers the source's two queries per window from scripted state.

    `covered` says which window ends the exporter ran over, in which namespace; `sizes`
    maps a window end to each bucket's average size in bytes.
    """

    def __init__(self, *, covered=lambda end, namespace: True, sizes=None):
        self.covered = covered
        self.sizes = sizes or (lambda end, namespace: {})
        self.queries: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        query = request.url.params["query"]
        end = datetime.strptime(request.url.params["time"], "%Y-%m-%dT%H:%M:%SZ")
        self.queries.append(query)
        namespace = query.split('namespace="', 1)[1].split('"', 1)[0]
        if query.startswith("count("):
            result = [{"metric": {}, "value": [0, "1"]}] if self.covered(end, namespace) else []
        else:
            result = [
                {"metric": {"bucket": bucket}, "value": [0, str(size)]}
                for bucket, size in self.sizes(end, namespace).items()
            ]
        return httpx.Response(200, json={"data": {"result": result}})

    def source(self, namespace: str = NAMESPACE) -> BucketSizeSource:
        client = PrometheusClient(
            "http://prometheus", client=httpx.Client(transport=httpx.MockTransport(self.handler))
        )
        return BucketSizeSource(client, namespace=namespace)


def _deployment(session):
    user = make_accepted_user(session, f"{uuid4().hex[:8]}@example.com")
    return make_bare_deployment(session, user.id)


def _bucket(deployment) -> str:
    return f"dep-{deployment.id}"


def _samples(session) -> dict[tuple[str, datetime], Decimal]:
    rows = session.exec(
        select(UsageSubjectORM.ref, UsageSampleORM.window_start, UsageSampleORM.value)
        .join(UsageSubjectORM, UsageSubjectORM.id == UsageSampleORM.subject_id)
        .join(UsageMetricORM, UsageMetricORM.id == UsageSampleORM.metric_id)
        .where(UsageMetricORM.name == "object_storage_byte_hours")
    ).all()
    return {(ref, start): value for ref, start, value in rows}


def _run(session, settings, fake: FakePrometheus, *, now: datetime = NOW):
    return sample_once(session, None, now=now, settings=settings, sources=[fake.source()])


# values


def test_a_bucket_of_constant_size_records_its_size_times_the_window(
    db_session, seeded_catalog, settings
):
    bucket = _bucket(_deployment(db_session))
    _run(db_session, settings, FakePrometheus(sizes=lambda end, ns: {bucket: 2 * GIB}))

    recorded = _samples(db_session)
    assert recorded[(bucket, WINDOW)] == Decimal(2 * GIB)
    # Six windows from the lookback, 08:00 through 13:00.
    assert len(recorded) == 6


def test_an_empty_bucket_is_not_recorded(db_session, seeded_catalog, settings):
    bucket = _bucket(_deployment(db_session))
    _run(db_session, settings, FakePrometheus(sizes=lambda end, ns: {bucket: 0}))

    assert _samples(db_session) == {}
    assert not db_session.exec(select(UsageSubjectORM)).all()
    # Measured as empty, which is progress.
    assert last_recorded_window(db_session, POSITION) is None


def test_a_bucket_emptied_mid_window_is_recorded_at_its_average(
    db_session, seeded_catalog, settings
):
    """1 GiB for the first half of 13:00, nothing after: Prometheus averages that to half,
    and the empty windows after it record nothing."""
    bucket = _bucket(_deployment(db_session))

    def sizes(end, ns):
        if end <= WINDOW:
            return {bucket: GIB}
        return {bucket: GIB // 2} if end == datetime(2026, 10, 7, 14) else {bucket: 0}

    _run(db_session, settings, FakePrometheus(sizes=sizes), now=datetime(2026, 10, 7, 16, 30))

    recorded = _samples(db_session)
    assert recorded[(bucket, WINDOW)] == Decimal(GIB // 2)
    assert (bucket, datetime(2026, 10, 7, 14)) not in recorded
    assert (bucket, datetime(2026, 10, 7, 15)) not in recorded


def test_the_value_query_averages_across_exporter_restarts(db_session, seeded_catalog, settings):
    """A restart mid-window publishes the same bucket from a new `instance`; the average
    must be over all of its samples, as one series per bucket."""
    fake = FakePrometheus()
    _run(db_session, settings, fake)
    values = [q for q in fake.queries if not q.startswith("count(")]
    assert values
    for query in values:
        assert "sum by (bucket) (sum_over_time(" in query
        assert "/ sum by (bucket) (count_over_time(" in query


# usable windows


def test_a_window_without_the_exporter_records_nothing_and_moves_nothing(
    db_session, seeded_catalog, settings
):
    bucket = _bucket(_deployment(db_session))
    fake = FakePrometheus(covered=lambda end, ns: False, sizes=lambda end, ns: {bucket: GIB})

    run = _run(db_session, settings, fake)

    assert run.windows_recorded == 0 and run.windows_skipped == 1
    assert not db_session.exec(select(UsageSampleORM)).all()
    assert last_recorded_window(db_session, POSITION) is None


def test_an_environment_without_buckets_still_has_usable_windows(
    db_session, seeded_catalog, settings
):
    run = _run(db_session, settings, FakePrometheus())

    assert run.windows_recorded == 6 and run.windows_skipped == 0
    assert not db_session.exec(select(UsageSampleORM)).all()


def test_another_namespaces_exporter_does_not_make_a_window_usable(
    db_session, seeded_catalog, settings
):
    bucket = _bucket(_deployment(db_session))
    fake = FakePrometheus(
        covered=lambda end, ns: ns == "caelus-garage",
        sizes=lambda end, ns: {bucket: GIB} if ns == "caelus-garage" else {},
    )

    run = _run(db_session, settings, fake)

    assert run.windows_skipped == 1
    assert _samples(db_session) == {}
    assert fake.queries and all(f'namespace="{NAMESPACE}"' in q for q in fake.queries)


def test_the_source_refuses_to_run_unscoped():
    with pytest.raises(ValueError):
        BucketSizeSource(PrometheusClient("http://prometheus"), namespace="")


# attribution


def test_a_bucket_is_a_bucket_subject_attributed_to_the_deployment_its_name_carries(
    db_session, seeded_catalog, settings
):
    deployment = _deployment(db_session)
    bucket = _bucket(deployment)
    _run(db_session, settings, FakePrometheus(sizes=lambda end, ns: {bucket: GIB}))

    subject = db_session.exec(select(UsageSubjectORM).where(UsageSubjectORM.ref == bucket)).one()
    assert (subject.kind, subject.namespace, subject.deployment_id) == (
        "bucket",
        NAMESPACE,
        deployment.id,
    )


def test_an_unknown_deployment_is_dropped_and_the_others_recorded(
    db_session, seeded_catalog, settings
):
    known = _bucket(_deployment(db_session))
    unknown = f"dep-{uuid4()}"
    _run(db_session, settings, FakePrometheus(sizes=lambda end, ns: {known: GIB, unknown: GIB}))

    assert {ref for ref, _ in _samples(db_session)} == {known}
    assert last_recorded_window(db_session, POSITION) == WINDOW


@pytest.mark.parametrize(
    "name",
    [
        "artifacts",
        "dep-",
        "dep-not-a-uuid",
        "dep-123",
        "xdep-5006d4fd-b458-48dc-bd90-20f1cac6ee85",
        "dep-5006d4fdb45848dcbd9020f1cac6ee85",
    ],
)
def test_a_malformed_name_is_dropped(db_session, seeded_catalog, settings, name):
    known = _bucket(_deployment(db_session))
    _run(db_session, settings, FakePrometheus(sizes=lambda end, ns: {known: GIB, name: GIB}))

    assert {ref for ref, _ in _samples(db_session)} == {known}


def test_names_parse_only_as_dep_and_a_lowercase_uuid():
    deployment_id = uuid4()
    assert deployment_id_of(f"dep-{deployment_id}") == deployment_id
    assert deployment_id_of(f"dep-{deployment_id}".upper()) is None
    assert deployment_id_of(f"dep-{deployment_id}-x") is None


@pytest.mark.parametrize(
    "deleted_at, recorded",
    [
        (datetime(2026, 10, 7, 13, 20), False),  # mid-window
        (datetime(2026, 10, 7, 14), True),  # exactly as the window ends
        (datetime(2026, 10, 7, 14, 10), True),  # after the window
    ],
)
def test_a_window_ending_after_deletion_is_not_recorded(
    db_session, seeded_catalog, deleted_at, recorded
):
    deployment = _deployment(db_session)
    deployment.deleted_at = deleted_at
    db_session.add(deployment)
    db_session.commit()
    bucket = _bucket(deployment)
    source = FakePrometheus(sizes=lambda end, ns: {bucket: GIB}).source()

    observed = source.read(db_session, WINDOW, window_seconds=HOUR)
    assert bool(list(observed)) is recorded


def test_catch_up_records_the_windows_before_deletion(db_session, seeded_catalog, settings):
    """Recording stopped at 10:00, the deployment was deleted at 14:20, and recording
    resumed at 16:00: 10:00-14:00 are recorded, 14:00-15:00 is not."""
    deployment = _deployment(db_session)
    deployment.deleted_at = datetime(2026, 10, 7, 14, 20)
    db_session.add(deployment)
    db_session.commit()
    bucket = _bucket(deployment)
    fake = FakePrometheus(sizes=lambda end, ns: {bucket: GIB})
    _run(db_session, settings, fake, now=datetime(2026, 10, 7, 10, 30))

    _run(db_session, settings, fake, now=datetime(2026, 10, 7, 16, 30))

    windows = {start for _, start in _samples(db_session)}
    assert {datetime(2026, 10, 7, h) for h in (10, 11, 12, 13)} <= windows
    assert not {datetime(2026, 10, 7, 14), datetime(2026, 10, 7, 15)} & windows


# registration and independence


def test_the_bucket_source_is_registered_only_when_its_namespace_is_set(settings):
    client = opencost_client()
    unset = settings.model_copy(update={"usage_bucket_namespace": ""})
    configured = settings.model_copy(update={"usage_bucket_namespace": NAMESPACE})

    assert "buckets" not in [s.name for s in sampler.default_sources(client, unset)]
    sources = sampler.default_sources(client, configured)
    (buckets,) = [s for s in sources if s.name == "buckets"]
    assert buckets.namespace == NAMESPACE


def test_a_stalled_bucket_source_does_not_hold_back_the_others(
    db_session, seeded_catalog, tenants, settings  # noqa: F811
):
    deployment = _deployment_with_database(db_session)
    from app.services import relational_storage

    name = relational_storage.database_name(deployment)
    databases = FakeDatabasePrometheus(sizes=lambda end: {name: GIB}).source()
    buckets = FakePrometheus(covered=lambda end, ns: False).source()
    containers = OpenCostSource(opencost_client(), environment="dev")

    run = sample_once(
        db_session, None, now=NOW, settings=settings, sources=[buckets, containers, databases]
    )

    assert run.windows_skipped == 1
    assert last_recorded_window(db_session, POSITION) is None
    assert last_recorded_window(db_session) == WINDOW
    assert last_recorded_window(db_session, databases.position_metrics) == WINDOW


# cost per window


def test_confirmation_is_one_statement_per_chunk_of_buckets(db_session, seeded_catalog):
    """2,500 buckets: three joins, then the ledger's own subject upsert and sample insert
    for the one chunk of buckets that are this environment's."""
    known = [_bucket(_deployment(db_session)) for _ in range(3)]
    sizes = {f"dep-{uuid4()}": GIB for _ in range(2500 - len(known))} | {b: GIB for b in known}
    source = FakePrometheus(sizes=lambda end, ns: sizes).source()

    statements: list[str] = []

    def count(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", count)
    try:
        written = record_source_window(
            db_session, source, WINDOW, window_seconds=HOUR, observed_at=NOW
        )
    finally:
        event.remove(engine, "before_cursor_execute", count)

    assert written == len(known)
    joins = [s for s in statements if "unnest(CAST(%(buckets)s" in s]
    assert len(joins) == 3
    others = [s for s in statements if s not in joins]
    # The catalog read, then one upsert of subjects and one insert of samples.
    assert len(others) == 3, others
