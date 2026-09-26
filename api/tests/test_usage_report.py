"""Reading the ledger back: bucketed, grouped and priced at the rate of the day."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlmodel import select

from app.models import (
    ProductORM,
    ProductTemplateVersionORM,
    UsageDimension,
    UsageBucket,
    UsageSubjectORM,
    UserORM,
)
from app.models.core import _utcnow
from app.services.errors import ValidationException
from app.services.usage import ledger
from app.services.usage.ledger import SampleRow
from app.services.usage.report import current_month, query_usage
from tests.conftest import USER_EMAIL, make_deployment_with_release
from tests.usage_fixtures import GIB, add_rate, seeded_catalog, seeded_rates  # noqa: F401

pytestmark = pytest.mark.usefixtures("seeded_rates")

DAY = datetime(2026, 9, 23)
BOTH = {UsageDimension.DEPLOYMENT, UsageDimension.METRIC}


def _template(session, product_name: str) -> int:
    product = ProductORM(name=product_name, created_at=_utcnow())
    session.add(product)
    session.flush()
    template = ProductTemplateVersionORM(
        product_id=product.id, chart_ref="oci://example/chart", chart_version="1.0.0"
    )
    session.add(template)
    session.flush()
    return template.id


def _deployment(session, user: UserORM, name: str, template_id: int):
    deployment = make_deployment_with_release(
        session,
        user_id=user.id,
        desired_template_id=template_id,
        name=name,
        hostname=f"{name}.example.test",
        namespace=f"ns-{uuid4().hex[:8]}",
    )
    session.flush()
    return deployment


def _subject(session, namespace: str, deployment_id=None) -> int:
    subject = UsageSubjectORM(
        kind="container",
        ref=f"{namespace}/Deployment/app/{uuid4().hex[:6]}",
        namespace=namespace,
        deployment_id=deployment_id,
    )
    session.add(subject)
    session.flush()
    return subject.id


def _record(session, subject_id: int, hour: int, **values: str) -> None:
    ledger.record_samples(
        session,
        [
            SampleRow(
                subject_id=subject_id,
                metric=metric,
                window_start=DAY + timedelta(hours=hour),
                interval_seconds=3600,
                value=Decimal(value),
            )
            for metric, value in values.items()
        ],
        observed_at=_utcnow(),
    )


@pytest.fixture
def ledger_data(db_session):
    """Two deployments for one user, plus usage that must never show up."""
    user = db_session.exec(select(UserORM).where(UserORM.email == USER_EMAIL)).first()
    if user is None:
        user = UserORM(email=USER_EMAIL)
        db_session.add(user)
        db_session.flush()
    other = UserORM(email="someone-else@example.com")
    db_session.add(other)
    db_session.flush()

    wiki = _template(db_session, "Wiki")
    postgres = _template(db_session, "Postgres")
    web = _deployment(db_session, user, "web", wiki)
    db = _deployment(db_session, user, "db", postgres)
    foreign = _deployment(db_session, other, "foreign", wiki)

    web_subject = _subject(db_session, web.namespace, web.id)
    for hour in (0, 1):
        _record(
            db_session,
            web_subject,
            hour,
            cpu_core_hours="0.5",
            ram_byte_hours=str(GIB),
            cpu_usage_cores_avg="0.2",  # a gauge: never reported
            network_transmit_bytes="1000",  # unpriced: not billable
        )
    _record(db_session, _subject(db_session, db.namespace, db.id), 1, cpu_core_hours="2")
    _record(
        db_session,
        _subject(db_session, foreign.namespace, foreign.id),
        0,
        cpu_core_hours="100",
    )
    _record(db_session, _subject(db_session, "kube-system"), 0, cpu_core_hours="100")
    db_session.commit()
    return user, web, db


def _query(session, user, **kwargs):
    kwargs.setdefault("start", DAY)
    kwargs.setdefault("end", DAY + timedelta(days=1))
    return query_usage(session, user_id=user.id, **kwargs)


def _as_dicts(report):
    return [dict(zip(report.columns, row)) for row in report.rows]


def test_usage_is_summed_per_bucket_and_priced(db_session, ledger_data):
    user, web, db = ledger_data
    report = _query(db_session, user, bucket=UsageBucket.DAY, group_by=BOTH)

    assert report.columns == [
        "window_start",
        "deployment_id",
        "deployment_name",
        "deployment_hostname",
        "metric",
        "unit",
        "value",
        "cost",
    ]
    rows = {(r["deployment_name"], r["metric"]): r for r in _as_dicts(report)}
    assert set(rows) == {
        ("web", "cpu_core_hours"),
        ("web", "ram_byte_hours"),
        ("db", "cpu_core_hours"),
    }
    assert rows["web", "cpu_core_hours"]["value"] == "1"
    assert rows["web", "cpu_core_hours"]["cost"] == "0.01"
    assert rows["web", "ram_byte_hours"]["cost"] == "0.004"
    assert rows["db", "cpu_core_hours"]["cost"] == "0.02"
    assert rows["db", "cpu_core_hours"]["deployment_id"] == db.id
    assert rows["db", "cpu_core_hours"]["deployment_hostname"] == "db.example.test"
    assert report.currency == "EUR"


def test_hourly_buckets_keep_windows_apart(db_session, ledger_data):
    user, _, _ = ledger_data
    report = _query(db_session, user, bucket=UsageBucket.HOUR, group_by=set())

    assert report.columns == ["window_start", "cost"]
    assert report.rows == [
        [DAY, "0.007"],
        [DAY + timedelta(hours=1), "0.027"],
    ]


def test_without_the_metric_dimension_only_cost_is_reported(db_session, ledger_data):
    """Core-hours and byte-hours do not add up; their costs do."""
    user, _, _ = ledger_data
    report = _query(db_session, user, group_by={UsageDimension.DEPLOYMENT})

    assert report.columns == [
        "window_start", "deployment_id", "deployment_name", "deployment_hostname", "cost",
    ]
    costs = {r["deployment_name"]: r["cost"] for r in _as_dicts(report)}
    assert costs == {"web": "0.014", "db": "0.02"}


def test_a_sample_is_priced_at_the_rate_in_effect_for_its_window(db_session, ledger_data):
    """A new rate is a new row; the hour before it keeps the old price."""
    user, _, _ = ledger_data
    add_rate(db_session, "cpu_core_hours", DAY + timedelta(hours=1), Decimal("1"))
    report = _query(
        db_session,
        user,
        bucket=UsageBucket.HOUR,
        group_by=set(),
        metrics={"cpu_core_hours"},
    )

    assert report.rows == [
        [DAY, "0.005"],
        [DAY + timedelta(hours=1), "2.5"],
    ]


def test_a_deleted_deployment_keeps_its_usage(db_session, ledger_data):
    user, web, _ = ledger_data
    web.deleted_at = _utcnow()
    db_session.add(web)
    db_session.commit()

    report = _query(db_session, user, group_by={UsageDimension.DEPLOYMENT})

    assert "web" in {r["deployment_name"] for r in _as_dicts(report)}


def test_filters_narrow_to_one_deployment_and_metric(db_session, ledger_data):
    user, web, _ = ledger_data
    report = _query(
        db_session, user, group_by=BOTH, deployment_id=web.id, metrics={"ram_byte_hours"}
    )

    assert [(r["deployment_name"], r["metric"]) for r in _as_dicts(report)] == [
        ("web", "ram_byte_hours")
    ]


def test_unmeasured_buckets_are_absent_and_the_ledger_end_is_reported(db_session, ledger_data):
    user, _, _ = ledger_data
    report = _query(
        db_session, user, start=DAY - timedelta(days=3), end=DAY + timedelta(days=3)
    )

    assert {row[0] for row in report.rows} == {DAY}
    assert report.recorded_through == DAY + timedelta(hours=2)


@pytest.mark.parametrize(
    "start, end, bucket",
    [
        (DAY, DAY, UsageBucket.DAY),
        (DAY, DAY + timedelta(days=365), UsageBucket.HOUR),
    ],
)
def test_malformed_ranges_are_refused(db_session, ledger_data, start, end, bucket):
    user, _, _ = ledger_data
    with pytest.raises(ValidationException):
        _query(db_session, user, start=start, end=end, bucket=bucket)


def test_current_month_rolls_over_the_year():
    assert current_month(datetime(2026, 12, 15)) == (
        datetime(2026, 12, 1),
        datetime(2027, 1, 1),
    )


def _params(**extra):
    return {"start": "2026-09-23T00:00:00Z", "end": "2026-09-24T00:00:00Z", **extra}


def test_the_api_reports_usage(user_client, ledger_data):
    client, _ = user_client
    user, _, _ = ledger_data
    response = client.get(
        f"/api/users/{user.id}/usage", params=_params(group_by="metric")
    )

    assert response.status_code == 200
    body = response.json()
    assert body["columns"] == ["window_start", "metric", "unit", "value", "cost"]
    assert [row[1] for row in body["rows"]] == ["cpu_core_hours", "ram_byte_hours"]


def test_the_api_serves_csv_on_request(user_client, ledger_data):
    client, _ = user_client
    user, _, _ = ledger_data
    response = client.get(
        f"/api/users/{user.id}/usage",
        params=_params(group_by=""),
        headers={"Accept": "text/csv"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    header, row = response.text.strip().split("\n")
    assert header == "window_start,cost"
    assert row.startswith("2026-09-23T00:00:00Z,")


def test_the_csv_names_deployments_by_hostname(user_client, ledger_data):
    """External consumers get a readable name without a second lookup."""
    client, _ = user_client
    user, _, _ = ledger_data
    response = client.get(
        f"/api/users/{user.id}/usage",
        params=_params(group_by="deployment"),
        headers={"Accept": "text/csv"},
    )

    lines = response.text.strip().split("\n")
    assert lines[0] == "window_start,deployment_id,deployment_name,deployment_hostname,cost"
    assert {line.split(",")[3] for line in lines[1:]} == {"web.example.test", "db.example.test"}


def test_the_api_refuses_another_accounts_usage(user_client, ledger_data):
    client, _ = user_client
    response = client.get("/api/users/999999/usage", params=_params())
    assert response.status_code == 403


def test_the_api_refuses_an_unknown_dimension(user_client, ledger_data):
    client, _ = user_client
    user, _, _ = ledger_data
    response = client.get(
        f"/api/users/{user.id}/usage", params=_params(group_by="container")
    )
    assert response.status_code == 400


def test_every_account_is_reported_when_no_user_is_given(db_session, ledger_data):
    report = query_usage(
        db_session,
        user_id=None,
        start=DAY,
        end=DAY + timedelta(days=1),
        group_by={UsageDimension.PRODUCT},
    )

    assert report.user_id is None
    assert report.columns == ["window_start", "product_id", "product_name", "cost"]
    costs = {r["product_name"]: r["cost"] for r in _as_dicts(report)}
    # Both accounts' wikis add up; platform overhead belongs to no product.
    assert costs == {"Wiki": "1.014", "Postgres": "0.02"}


def test_deployments_cannot_be_grouped_across_every_account(db_session, ledger_data):
    """The response would grow with the customer base."""
    _, web, _ = ledger_data
    with pytest.raises(ValidationException):
        query_usage(
            db_session,
            user_id=None,
            start=DAY,
            end=DAY + timedelta(days=1),
            group_by={UsageDimension.DEPLOYMENT},
        )

    scoped = query_usage(
        db_session,
        user_id=None,
        start=DAY,
        end=DAY + timedelta(days=1),
        group_by={UsageDimension.DEPLOYMENT},
        deployment_id=web.id,
    )
    assert [r["deployment_name"] for r in _as_dicts(scoped)] == ["web"]


def test_the_admin_api_reports_across_accounts_by_product(client, ledger_data):
    response = client.get("/api/usage", params=_params())

    assert response.status_code == 200
    body = response.json()
    assert body["columns"][:3] == ["window_start", "product_id", "product_name"]
    assert {row[2] for row in body["rows"]} == {"Wiki", "Postgres"}
    assert all(isinstance(row[1], int) for row in body["rows"])


def test_the_admin_api_narrows_to_one_account(client, ledger_data):
    user, _, _ = ledger_data
    response = client.get(
        "/api/usage", params=_params(group_by="deployment", user_id=user.id)
    )

    assert response.status_code == 200
    assert {row[2] for row in response.json()["rows"]} == {"web", "db"}


def test_the_admin_api_refuses_deployments_across_accounts(client, ledger_data):
    response = client.get("/api/usage", params=_params(group_by="deployment"))
    assert response.status_code == 400


def test_the_admin_api_is_for_administrators(user_client, ledger_data):
    client, _ = user_client
    assert client.get("/api/usage", params=_params()).status_code == 403


# builds


def test_a_builds_usage_is_reported_under_its_deployment_and_product(db_session, ledger_data):
    """Recorded by the build worker, and reported with no change to reporting --
    including after the deployment is gone."""
    from app.config import CaelusSettings
    from app.models import BuildORM
    from app.services.usage.builds import record_settled_builds

    user, _, db = ledger_data
    build = BuildORM(
        artifact_id=uuid4().hex,
        deployment_id=db.id,
        status="succeeded",
        job_id="build-x",
        started_at=DAY + timedelta(hours=1, minutes=10),
        finished_at=DAY + timedelta(hours=1, minutes=13),
        usage_cpu_seconds=7200.0,  # two core-hours in three minutes: over the floor
        usage_memory_byte_seconds=0,
        usage_memory_peak_bytes=0,
        usage_started_at=DAY + timedelta(hours=1, minutes=10),
        usage_finished_at=DAY + timedelta(hours=1, minutes=12),
    )
    db_session.add(build)
    db_session.commit()
    record_settled_builds(
        db_session, now=DAY + timedelta(hours=3), settings=CaelusSettings(_env_file=None)
    )

    by_deployment = {
        r["deployment_name"]: r["cost"]
        for r in _as_dicts(_query(db_session, user, group_by={UsageDimension.DEPLOYMENT}))
    }
    # db's own 2 core-hours and the build's 2 at 0.01, plus the build's memory at
    # its floor: 1 GiB held for 2 minutes at 0.002 per GiB-hour.
    expected = Decimal("0.04") + Decimal("0.002") / 30
    assert abs(Decimal(by_deployment["db"]) - expected) < Decimal("1e-20")

    by_product = {
        r["product_name"]: r["cost"]
        for r in _as_dicts(
            query_usage(
                db_session, user_id=None, start=DAY, end=DAY + timedelta(days=1),
                group_by={UsageDimension.PRODUCT},
            )
        )
    }
    assert Decimal(by_product["Postgres"]) > Decimal("0.04")

    db.deleted_at = _utcnow()
    db_session.add(db)
    db_session.commit()
    after = {
        r["deployment_name"]: r["cost"]
        for r in _as_dicts(_query(db_session, user, group_by={UsageDimension.DEPLOYMENT}))
    }
    assert after["db"] == by_deployment["db"]
