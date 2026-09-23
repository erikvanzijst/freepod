"""The usage worker process and its CLI entry point."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlmodel import select

from app.config import CaelusSettings, get_settings
from app.models import (
    ProductORM,
    ProductTemplateVersionORM,
    UsageSampleORM,
    UserORM,
)
from app.services.usage import OpenCostClient
from app.usage_worker import run_usage_worker
from tests.conftest import make_deployment_with_release
from tests.usage_fixtures import seeded_catalog  # noqa: F401

FIXTURES = Path(__file__).parent / "fixtures"
HOUR = 3600
COVERED = {"data": {"result": [{"metric": {}, "value": [1790161200, "126"]}]}}


@pytest.fixture
def settings() -> CaelusSettings:
    return CaelusSettings(
        **{
            **get_settings().model_dump(),
            "opencost_base_url": "http://opencost:9003",
            "prometheus_base_url": "http://prometheus",
            "usage_window_seconds": HOUR,
            "usage_settle_seconds": 300,
            "usage_first_run_lookback_seconds": 3 * HOUR,
            "usage_max_windows_per_pass": 24,
            "usage_worker_interval_seconds": 0.01,
        }
    )


def _client() -> OpenCostClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/api/v1/query" in request.url.path:
            return httpx.Response(200, json=COVERED)
        payload = json.loads((FIXTURES / "opencost_allocation.json").read_text())
        window = payload["data"][0]
        start = datetime.strptime(
            request.url.params["window"].split(",")[0], "%Y-%m-%dT%H:%M:%SZ"
        )
        end = start + timedelta(seconds=HOUR)
        stamp = lambda m: m.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
        for entry in window.values():
            entry["window"] = {"start": stamp(start), "end": stamp(end)}
            entry["start"], entry["end"] = stamp(start), stamp(end)
        return httpx.Response(
            200,
            content=json.dumps({"code": 200, "data": [window]}),
            headers={"content-type": "application/json"},
        )

    return OpenCostClient(
        "http://opencost:9003",
        prometheus_url="http://prometheus",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


@pytest.fixture
def tenant(db_session):
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


def test_a_single_pass_records_a_window(db_session, seeded_catalog, tenant, settings):
    emitted: list[dict] = []
    run_usage_worker(
        settings=settings, client=_client(), emit=emitted.append, max_passes=1
    )

    samples = db_session.exec(select(UsageSampleORM)).all()
    assert samples
    assert emitted
    assert emitted[0]["windows_recorded"] > 0
    assert emitted[0]["samples_written"] == len(samples)


def test_a_second_pass_finds_nothing_new(db_session, seeded_catalog, tenant, settings):
    """Only one pass an hour finds work; the rest return immediately."""
    run_usage_worker(settings=settings, client=_client(), max_passes=1)
    before = len(db_session.exec(select(UsageSampleORM)).all())

    run_usage_worker(settings=settings, client=_client(), max_passes=1)
    assert len(db_session.exec(select(UsageSampleORM)).all()) == before


def test_a_failing_source_does_not_stop_the_loop(
    db_session, seeded_catalog, tenant, settings
):
    """A pass that cannot reach its source is logged and retried next tick."""
    unreachable = OpenCostClient(
        "http://opencost:9003",
        prometheus_url="http://prometheus",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: (_ for _ in ()).throw(httpx.ConnectError("down"))
            )
        ),
    )
    run_usage_worker(settings=settings, client=unreachable, max_passes=2)
    assert not db_session.exec(select(UsageSampleORM)).all()


def test_the_command_refuses_to_start_unconfigured(cli_runner, monkeypatch):
    """Recording nothing silently is the failure mode this guards."""
    monkeypatch.setenv("CAELUS_OPENCOST_BASE_URL", "")
    monkeypatch.setenv("CAELUS_PROMETHEUS_BASE_URL", "")
    get_settings.cache_clear()

    runner, cli_app = cli_runner
    result = runner.invoke(cli_app, ["usage-worker", "--once"])
    assert result.exit_code == 1
    assert "OPENCOST_BASE_URL" in result.output
    get_settings.cache_clear()


def test_the_command_rejects_a_non_positive_interval(cli_runner, monkeypatch):
    monkeypatch.setenv("CAELUS_OPENCOST_BASE_URL", "http://opencost:9003")
    monkeypatch.setenv("CAELUS_PROMETHEUS_BASE_URL", "http://prometheus")
    get_settings.cache_clear()

    runner, cli_app = cli_runner
    result = runner.invoke(cli_app, ["usage-worker", "--interval-seconds", "0"])
    assert result.exit_code == 1
    assert "must be > 0" in result.output
    get_settings.cache_clear()
