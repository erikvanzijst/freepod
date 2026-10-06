"""Tenant database sizes as a usage source, and the sampler running it beside OpenCost."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from sqlmodel import select

from app.config import CaelusSettings, get_settings
from app.models import (
    DeploymentDatabaseORM,
    PlanORM,
    PlanTemplateVersionORM,
    ProductORM,
    ProductTemplateVersionORM,
    SubscriptionORM,
    UsageMetricORM,
    UsageSampleORM,
    UsageSubjectORM,
    UserORM,
)
from app.models.billing import BillingInterval
from app.services import relational_storage
from app.services.usage import sampler
from app.services.usage.databases import DatabaseSizeSource
from app.services.usage.prometheus import PrometheusClient
from app.services.usage.sampler import (
    OpenCostSource,
    last_recorded_window,
    sample_once,
)
from tests.conftest import make_deployment_with_release
from tests.test_usage_sampler import _client as opencost_client
from tests.test_usage_sampler import tenants  # noqa: F401
from tests.usage_fixtures import seeded_catalog  # noqa: F401

HOUR = 3600
GIB = 2**30
NAMESPACE = "caelus-dev"
NOW = datetime(2026, 10, 6, 14, 30)


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

    `covered` says which window ends the exporter published over; `sizes` maps a
    window end to each database's average size in bytes.
    """

    def __init__(self, *, covered=lambda end: True, sizes=None, fail=False):
        self.covered = covered
        self.sizes = sizes or (lambda end: {})
        self.fail = fail
        self.queries: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.fail:
            raise httpx.ConnectError("down")
        query = request.url.params["query"]
        end = datetime.strptime(request.url.params["time"], "%Y-%m-%dT%H:%M:%SZ")
        self.queries.append(query)
        if query.startswith("count("):
            result = [{"metric": {}, "value": [0, "3"]}] if self.covered(end) else []
        else:
            result = [
                {"metric": {"datname": name, "namespace": NAMESPACE}, "value": [0, str(size)]}
                for name, size in self.sizes(end).items()
            ]
        return httpx.Response(200, json={"data": {"result": result}})

    def source(self, namespace: str = NAMESPACE) -> DatabaseSizeSource:
        client = PrometheusClient(
            "http://prometheus", client=httpx.Client(transport=httpx.MockTransport(self.handler))
        )
        return DatabaseSizeSource(client, namespace=namespace)


def _deployment_with_database(session, *, database_bytes: int | None = 100 * 2**20):
    """A deployment, its plan and its `deployment_database` row."""
    token = uuid4().hex[:8]
    user = UserORM(email=f"{token}@example.com")
    product = ProductORM(name=f"custom-{token}")
    session.add(user)
    session.add(product)
    session.commit()
    template = ProductTemplateVersionORM(
        product_id=product.id, chart_ref="oci://example/custom", chart_version="1.0.0"
    )
    plan = PlanORM(name=f"plan-{token}", product_id=product.id)
    session.add(template)
    session.add(plan)
    session.flush()
    ptv = PlanTemplateVersionORM(
        plan_id=plan.id,
        price_cents=0,
        billing_interval=BillingInterval.MONTHLY,
        storage_bytes=0,
        database_bytes=database_bytes,
    )
    session.add(ptv)
    session.flush()
    subscription = SubscriptionORM(plan_template_id=ptv.id, user_id=user.id)
    session.add(subscription)
    session.flush()
    deployment = make_deployment_with_release(
        session,
        user_id=user.id,
        desired_template_id=template.id,
        subscription_id=subscription.id,
        name=f"app-{token}",
        namespace=f"ns-{token}",
    )
    session.commit()
    session.add(
        DeploymentDatabaseORM(
            deployment_id=deployment.id,
            db_name=relational_storage.database_name(deployment),
            role_name=relational_storage.role_name(deployment),
            password_encrypted="unused",
            key_id="unused",
        )
    )
    session.commit()
    session.refresh(deployment)
    return deployment


def _samples(session, metric: str) -> dict[tuple[str, datetime], Decimal]:
    rows = session.exec(
        select(UsageSubjectORM.ref, UsageSampleORM.window_start, UsageSampleORM.value)
        .join(UsageSubjectORM, UsageSubjectORM.id == UsageSampleORM.subject_id)
        .join(UsageMetricORM, UsageMetricORM.id == UsageSampleORM.metric_id)
        .where(UsageMetricORM.name == metric)
    ).all()
    return {(ref, start): value for ref, start, value in rows}


# trust (3.2)


def test_a_window_the_exporter_did_not_cover_records_nothing_and_moves_nothing(
    db_session, seeded_catalog, settings
):
    deployment = _deployment_with_database(db_session)
    name = relational_storage.database_name(deployment)
    prometheus = FakePrometheus(covered=lambda end: False, sizes=lambda end: {name: GIB})

    run = sample_once(db_session, None, now=NOW, settings=settings, sources=[prometheus.source()])

    assert run.windows_recorded == 0 and run.windows_skipped == 1
    assert not db_session.exec(select(UsageSampleORM)).all()
    assert last_recorded_window(db_session, "database") is None


def test_both_queries_are_scoped_to_the_configured_namespace(db_session, seeded_catalog, settings):
    prometheus = FakePrometheus()
    sample_once(
        db_session, None, now=NOW, settings=settings, sources=[prometheus.source("caelus")]
    )
    assert prometheus.queries
    assert all('namespace="caelus"' in query for query in prometheus.queries)


def test_the_source_refuses_to_run_unscoped():
    with pytest.raises(ValueError):
        DatabaseSizeSource(PrometheusClient("http://prometheus"), namespace="")


# values (3.3)


def test_a_full_window_records_its_average_size_as_byte_hours(db_session, seeded_catalog, settings):
    deployment = _deployment_with_database(db_session)
    name = relational_storage.database_name(deployment)
    prometheus = FakePrometheus(sizes=lambda end: {name: 2 * GIB})

    sample_once(db_session, None, now=NOW, settings=settings, sources=[prometheus.source()])

    recorded = _samples(db_session, "db_byte_hours")
    assert recorded[(name, datetime(2026, 10, 6, 13))] == Decimal(2 * GIB)
    # Six windows from the lookback, 08:00 through 13:00.
    assert len(recorded) == 6


def test_a_partly_covered_window_records_the_published_average_exactly(
    db_session, seeded_catalog, settings
):
    """The average is Prometheus's over what was published; recorded without rounding."""
    deployment = _deployment_with_database(db_session)
    name = relational_storage.database_name(deployment)
    prometheus = FakePrometheus(sizes=lambda end: {name: "7954959.333333333"})

    sample_once(db_session, None, now=NOW, settings=settings, sources=[prometheus.source()])

    assert _samples(db_session, "db_byte_hours")[(name, datetime(2026, 10, 6, 13))] == Decimal(
        "7954959.333333333"
    )


def test_a_database_absent_from_a_usable_window_records_nothing_not_zero(
    db_session, seeded_catalog, settings
):
    present = _deployment_with_database(db_session)
    absent = _deployment_with_database(db_session)
    prometheus = FakePrometheus(
        sizes=lambda end: {relational_storage.database_name(present): GIB}
    )

    sample_once(db_session, None, now=NOW, settings=settings, sources=[prometheus.source()])

    refs = {ref for ref, _ in _samples(db_session, "db_byte_hours")}
    assert refs == {relational_storage.database_name(present)}
    assert relational_storage.database_name(absent) not in refs


def test_the_value_query_selects_no_databases_by_name(db_session, seeded_catalog, settings):
    """Which databases are tenants' is answered by the records, not a name pattern."""
    prometheus = FakePrometheus()
    sample_once(db_session, None, now=NOW, settings=settings, sources=[prometheus.source()])
    values = [q for q in prometheus.queries if q.startswith("avg_over_time(")]
    assert values
    assert all("datname" not in query for query in values)


def test_the_servers_own_databases_are_not_recorded(db_session, seeded_catalog, settings):
    deployment = _deployment_with_database(db_session)
    name = relational_storage.database_name(deployment)
    prometheus = FakePrometheus(
        sizes=lambda end: {name: GIB, "postgres": GIB, "template0": GIB, "template1": GIB}
    )

    sample_once(db_session, None, now=NOW, settings=settings, sources=[prometheus.source()])

    assert {ref for ref, _ in _samples(db_session, "db_byte_hours")} == {name}
    assert {s.ref for s in db_session.exec(select(UsageSubjectORM)).all()} == {name}


# attribution and deletion (3.4)


def test_a_database_is_a_database_subject_attributed_to_its_deployment(
    db_session, seeded_catalog, settings
):
    deployment = _deployment_with_database(db_session)
    name = relational_storage.database_name(deployment)
    prometheus = FakePrometheus(sizes=lambda end: {name: GIB})

    sample_once(db_session, None, now=NOW, settings=settings, sources=[prometheus.source()])

    subject = db_session.exec(select(UsageSubjectORM).where(UsageSubjectORM.ref == name)).one()
    assert (subject.kind, subject.namespace, subject.deployment_id) == (
        "database",
        NAMESPACE,
        deployment.id,
    )


def test_an_unknown_database_is_not_recorded(db_session, seeded_catalog, settings):
    prometheus = FakePrometheus(sizes=lambda end: {"dpl_" + uuid4().hex: GIB})
    sample_once(db_session, None, now=NOW, settings=settings, sources=[prometheus.source()])
    assert not db_session.exec(select(UsageSubjectORM)).all()


@pytest.mark.parametrize(
    "deleted_at, recorded",
    [
        (datetime(2026, 10, 6, 13, 20), False),  # mid-window
        (datetime(2026, 10, 6, 14), True),  # exactly as the window ends
        (datetime(2026, 10, 6, 14, 10), True),  # after the window
    ],
)
def test_a_window_ending_after_deletion_is_not_recorded(
    db_session, seeded_catalog, settings, deleted_at, recorded
):
    deployment = _deployment_with_database(db_session)
    deployment.deleted_at = deleted_at
    db_session.add(deployment)
    db_session.commit()
    name = relational_storage.database_name(deployment)
    source = FakePrometheus(sizes=lambda end: {name: GIB}).source()

    rows = source.read(
        db_session, datetime(2026, 10, 6, 13), window_seconds=HOUR, observed_at=NOW
    )
    assert bool(rows) is recorded


def test_catch_up_records_the_windows_before_deletion(db_session, seeded_catalog, settings):
    deployment = _deployment_with_database(db_session)
    deployment.deleted_at = datetime(2026, 10, 6, 14, 20)
    db_session.add(deployment)
    db_session.commit()
    name = relational_storage.database_name(deployment)
    # The exporter was down from 10:00, when the source last recorded, until now.
    prometheus = FakePrometheus(sizes=lambda end: {name: GIB})
    sample_once(
        db_session,
        None,
        now=datetime(2026, 10, 6, 10, 30),
        settings=settings,
        sources=[prometheus.source()],
    )

    sample_once(
        db_session,
        None,
        now=datetime(2026, 10, 6, 16, 30),
        settings=settings,
        sources=[prometheus.source()],
    )

    windows = {start for _, start in _samples(db_session, "db_byte_hours")}
    assert {datetime(2026, 10, 6, h) for h in (10, 11, 12, 13)} <= windows
    assert not {datetime(2026, 10, 6, 14), datetime(2026, 10, 6, 15)} & windows


# allowance (3.5)


def test_the_plans_allowance_is_recorded_beside_the_size(db_session, seeded_catalog, settings):
    deployment = _deployment_with_database(db_session, database_bytes=100 * 2**20)
    name = relational_storage.database_name(deployment)
    prometheus = FakePrometheus(sizes=lambda end: {name: GIB})

    sample_once(db_session, None, now=NOW, settings=settings, sources=[prometheus.source()])

    window = (name, datetime(2026, 10, 6, 13))
    assert _samples(db_session, "db_allowance_byte_hours")[window] == Decimal(100 * 2**20)
    assert _samples(db_session, "db_byte_hours")[window] == Decimal(GIB)


def test_a_plan_without_an_allowance_still_records_the_size(db_session, seeded_catalog, settings):
    deployment = _deployment_with_database(db_session, database_bytes=None)
    name = relational_storage.database_name(deployment)
    prometheus = FakePrometheus(sizes=lambda end: {name: GIB})

    sample_once(db_session, None, now=NOW, settings=settings, sources=[prometheus.source()])

    assert _samples(db_session, "db_byte_hours")
    assert not _samples(db_session, "db_allowance_byte_hours")


# per-source positions (2.1)


def _seed(session, kind: str, window_start: datetime) -> None:
    subject = UsageSubjectORM(kind=kind, ref=f"{kind}-{uuid4().hex}", namespace="ns")
    session.add(subject)
    session.commit()
    metric = session.exec(select(UsageMetricORM)).first()
    session.add(
        UsageSampleORM(
            subject_id=subject.id,
            metric_id=metric.id,
            window_start=window_start,
            interval_seconds=HOUR,
            observed_at=window_start,
            value=Decimal(1),
        )
    )
    session.commit()


def test_a_newer_database_sample_does_not_advance_the_container_position(
    db_session, seeded_catalog
):
    _seed(db_session, "container", datetime(2026, 10, 6, 12))
    _seed(db_session, "database", datetime(2026, 10, 6, 15))
    assert last_recorded_window(db_session) == datetime(2026, 10, 6, 12)
    assert last_recorded_window(db_session, "container") == datetime(2026, 10, 6, 12)


def test_a_newer_container_sample_does_not_advance_the_database_position(
    db_session, seeded_catalog
):
    _seed(db_session, "container", datetime(2026, 10, 6, 15))
    _seed(db_session, "database", datetime(2026, 10, 6, 12))
    assert last_recorded_window(db_session, "database") == datetime(2026, 10, 6, 12)


# independent sources (2.3)


def _opencost(settings):
    return OpenCostSource(opencost_client(), environment="dev")


def test_an_unusable_database_window_leaves_containers_recorded(
    db_session, seeded_catalog, tenants, settings  # noqa: F811
):
    prometheus = FakePrometheus(covered=lambda end: False)
    run = sample_once(
        db_session,
        None,
        now=NOW,
        settings=settings,
        sources=[prometheus.source(), _opencost(settings)],
    )
    assert last_recorded_window(db_session) == datetime(2026, 10, 6, 13)
    assert last_recorded_window(db_session, "database") is None
    assert run.windows_skipped == 1


def test_an_opencost_outage_leaves_databases_recorded(db_session, seeded_catalog, settings):
    deployment = _deployment_with_database(db_session)
    name = relational_storage.database_name(deployment)
    prometheus = FakePrometheus(sizes=lambda end: {name: GIB})
    down = OpenCostSource(opencost_client(cover=False), environment="dev")

    sample_once(
        db_session, None, now=NOW, settings=settings, sources=[down, prometheus.source()]
    )

    assert last_recorded_window(db_session) is None
    assert last_recorded_window(db_session, "database") == datetime(2026, 10, 6, 13)


def test_a_raising_source_does_not_stop_the_other(
    db_session, seeded_catalog, tenants, settings  # noqa: F811
):
    class Broken:
        name = "broken"
        subject_kind = "database"

        def read(self, *args, **kwargs):
            raise RuntimeError("bug")

    run = sample_once(
        db_session, None, now=NOW, settings=settings, sources=[Broken(), _opencost(settings)]
    )
    assert run.failed_sources == ["broken"]
    assert last_recorded_window(db_session) == datetime(2026, 10, 6, 13)


# registration (3.6)


def test_the_database_source_is_registered_only_when_its_namespace_is_set(settings):
    client = opencost_client()
    unset = settings.model_copy(update={"usage_tenant_db_namespace": ""})
    configured = settings.model_copy(update={"usage_tenant_db_namespace": NAMESPACE})

    assert [s.name for s in sampler.default_sources(client, unset)] == ["opencost"]
    sources = sampler.default_sources(client, configured)
    assert [s.name for s in sources] == ["opencost", "databases"]
    assert sources[1].namespace == NAMESPACE


def test_the_database_window_is_on_the_same_grid_as_containers(db_session, seeded_catalog, settings):
    """Both sources record the same window starts, so they sum over any period."""
    deployment = _deployment_with_database(db_session)
    name = relational_storage.database_name(deployment)
    prometheus = FakePrometheus(sizes=lambda end: {name: GIB})
    sample_once(db_session, None, now=NOW, settings=settings, sources=[prometheus.source()])
    starts = {start for _, start in _samples(db_session, "db_byte_hours")}
    assert starts == {datetime(2026, 10, 6, 8) + timedelta(hours=h) for h in range(6)}
