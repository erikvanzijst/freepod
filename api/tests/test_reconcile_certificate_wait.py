"""Waiting for the account's certificate.

The reconcile defers rather than completing, because membership is derived from
the certificates that exist and a reconcile that finishes early writes a list
without this one and has no reason to write again — see
openspec/specs/account-tls-certificate/spec.md.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.config import CaelusSettings
from app.models import DeploymentORM, DeploymentReleaseORM
from app.services.jobs import JobService
from app.services.reconcile import DeploymentReconciler
from app.services.reconcile_constants import (
    DEPLOYMENT_STATUS_ERROR,
    DEPLOYMENT_STATUS_PROVISIONING,
    DEPLOYMENT_STATUS_READY,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
)
from tests.provisioner_utils import FakeProvisioner
from tests.test_reconcile_account_dns import ACCOUNT_EMAIL, _seed
from tests.conftest import make_accepted_user


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    settings = CaelusSettings(
        wildcard_domains=[],
        domain="dev.freepod.eu",
        account_cert_wait_budget_seconds=600,
        account_cert_defer_seconds=20,
        _env_file=None,
    )
    monkeypatch.setattr("app.services.reconcile.get_settings", lambda: settings)
    return settings


@pytest.fixture
def account(db_session):
    return make_accepted_user(db_session, ACCOUNT_EMAIL)


@pytest.fixture
def deployment_id(db_session, account):
    return _seed(db_session, account, hostname="app.dev.freepod.eu")


@pytest.fixture
def provisioner(monkeypatch):
    p = FakeProvisioner()
    monkeypatch.setattr("app.services.reconcile.default_provisioner", p)
    return p


def test_an_unissued_certificate_leaves_the_deployment_provisioning(
    db_session, deployment_id, provisioner
):
    provisioner.certificate_state = (False, "waiting for DNS-01 propagation")

    result = DeploymentReconciler(session=db_session).reconcile(
        deployment_id, queued_at=datetime.now(UTC)
    )

    assert result.deferred is True
    assert result.status == DEPLOYMENT_STATUS_PROVISIONING
    assert result.last_error is None


def test_a_deferred_reconcile_records_no_release_outcome(db_session, deployment_id, provisioner):
    """`ended_at` is written once, and the release has not ended."""
    provisioner.certificate_state = (False, "issuing")
    DeploymentReconciler(session=db_session).reconcile(
        deployment_id, queued_at=datetime.now(UTC)
    )

    deployment = db_session.get(DeploymentORM, deployment_id)
    release = db_session.get(DeploymentReleaseORM, deployment.desired_release_id)
    assert deployment.status == DEPLOYMENT_STATUS_PROVISIONING
    assert release.started_at is not None
    assert release.ended_at is None
    assert release.error is None


def test_the_retry_completes_once_the_certificate_is_issued(
    db_session, deployment_id, provisioner
):
    provisioner.certificate_state = (False, "issuing")
    first = DeploymentReconciler(session=db_session).reconcile(
        deployment_id, queued_at=datetime.now(UTC)
    )
    assert first.deferred is True

    provisioner.certificate_state = (True, None)
    second = DeploymentReconciler(session=db_session).reconcile(
        deployment_id, queued_at=datetime.now(UTC)
    )

    assert second.deferred is False
    assert second.status == DEPLOYMENT_STATUS_READY


def test_exhausting_the_budget_fails_the_deployment(db_session, deployment_id, provisioner):
    provisioner.certificate_state = (False, "the order is stuck")
    queued_long_ago = datetime.now(UTC) - timedelta(seconds=601)

    result = DeploymentReconciler(session=db_session).reconcile(
        deployment_id, queued_at=queued_long_ago
    )

    assert result.deferred is False
    assert result.status == DEPLOYMENT_STATUS_ERROR


def test_the_failure_names_the_certificate_not_the_release(
    db_session, deployment_id, provisioner
):
    provisioner.certificate_state = (False, "CAA record forbids this issuer")
    result = DeploymentReconciler(session=db_session).reconcile(
        deployment_id, queued_at=datetime.now(UTC) - timedelta(seconds=601)
    )

    assert "certificate" in result.last_error.lower()
    assert "acct-" in result.last_error
    assert "CAA record forbids this issuer" in result.last_error


def test_a_reconcile_with_no_budget_defers_forever_rather_than_failing(
    db_session, deployment_id, provisioner
):
    """The operator CLI passes no `queued_at`: it has no job to defer, so it
    reports rather than converting a wait into a failure."""
    provisioner.certificate_state = (False, "issuing")

    result = DeploymentReconciler(session=db_session).reconcile(deployment_id)

    assert result.deferred is True
    assert result.status == DEPLOYMENT_STATUS_PROVISIONING


def test_a_certificate_issued_after_a_failure_is_picked_up(
    db_session, deployment_id, provisioner
):
    provisioner.certificate_state = (False, "stuck")
    failed = DeploymentReconciler(session=db_session).reconcile(
        deployment_id, queued_at=datetime.now(UTC) - timedelta(seconds=601)
    )
    assert failed.status == DEPLOYMENT_STATUS_ERROR

    provisioner.certificate_state = (True, None)
    later = DeploymentReconciler(session=db_session).reconcile(
        deployment_id, queued_at=datetime.now(UTC)
    )

    assert later.status == DEPLOYMENT_STATUS_READY
    # Nothing deleted it in between; the reconcile asked and found it issued.
    assert ("ensure_account_certificate", {"fqdn": "alice.dev.freepod.eu"}) in provisioner.calls


# --- the queue half -------------------------------------------------------


def test_defer_returns_the_same_row_to_the_queue(db_session, deployment_id):
    jobs = JobService(db_session)
    job = jobs.claim_next_job(worker_id="w1")
    assert job.status == JOB_STATUS_RUNNING

    deferred = jobs.defer_job(job_id=job.id, delay=timedelta(seconds=20), worker_id="w1")

    assert deferred.id == job.id
    assert deferred.status == JOB_STATUS_QUEUED
    assert deferred.locked_by is None
    assert deferred.locked_at is None


def test_deferring_does_not_touch_the_attempt_count(db_session, deployment_id):
    """`attempt` counts lease expiries — how often a worker died holding this
    job. A deferral is the opposite of that."""
    jobs = JobService(db_session)
    job = jobs.claim_next_job(worker_id="w1")
    before = job.attempt

    deferred = jobs.defer_job(job_id=job.id, delay=timedelta(seconds=20), worker_id="w1")

    assert deferred.attempt == before


def test_a_deferred_job_is_not_claimable_before_its_time(db_session, deployment_id):
    jobs = JobService(db_session)
    job = jobs.claim_next_job(worker_id="w1")
    jobs.defer_job(job_id=job.id, delay=timedelta(seconds=300), worker_id="w1")

    assert jobs.claim_next_job(worker_id="w2") is None


def test_a_deferred_job_is_claimed_once_it_is_due(db_session, deployment_id):
    jobs = JobService(db_session)
    job = jobs.claim_next_job(worker_id="w1")
    jobs.defer_job(job_id=job.id, delay=timedelta(seconds=-1), worker_id="w1")

    claimed = jobs.claim_next_job(worker_id="w2")

    assert claimed is not None
    assert claimed.id == job.id


def test_deferring_never_trips_the_one_open_job_constraint(db_session, deployment_id):
    """A successor row would be refused; the same row going back is not."""
    jobs = JobService(db_session)
    job = jobs.claim_next_job(worker_id="w1")

    for _ in range(3):
        jobs.defer_job(job_id=job.id, delay=timedelta(seconds=-1), worker_id="w1")
        job = jobs.claim_next_job(worker_id="w1")

    open_jobs = jobs.list_jobs(
        deployment_id=deployment_id, statuses=[JOB_STATUS_QUEUED, JOB_STATUS_RUNNING]
    )
    assert len(open_jobs) == 1


def test_a_worker_that_lost_its_lease_cannot_defer(db_session, deployment_id):
    jobs = JobService(db_session)
    job = jobs.claim_next_job(worker_id="w1")

    unchanged = jobs.defer_job(job_id=job.id, delay=timedelta(seconds=20), worker_id="someone-else")

    assert unchanged.status == JOB_STATUS_RUNNING
    assert unchanged.locked_by == "w1"
