"""The reconciler's power branch (deployment-power-reconciliation,
deployment-release-ledger "A power change is not a release")."""

from __future__ import annotations

import pytest
from sqlmodel import select

from app.config import CaelusSettings
from app.models import DeploymentORM, DeploymentReleaseORM, DeploymentUpdate
from app.models.core import DeploymentPowerORM, DeploymentReconcileJobORM
from app.services import deployments as deployment_service
from app.services.reconcile import DeploymentReconciler
from tests.provisioner_utils import FakeProvisioner
from tests.test_reconcile_service import _seed_deployment
from tests.conftest import db_session  # noqa: F401


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setattr(
        "app.services.reconcile.get_settings",
        lambda: CaelusSettings(
            domain="example.test",
            tls_cluster_issuer="letsencrypt-http",
            parking_host="caelus-api.caelus.svc.cluster.local",
            _env_file=None,
        ),
    )


def _reconcile(db_session, provisioner=None) -> FakeProvisioner:
    provisioner = provisioner or FakeProvisioner()
    DeploymentReconciler(session=db_session, provisioner=provisioner).reconcile(_reconcile.deployment_id)
    db_session.expire_all()
    return provisioner


def _deployment(db_session) -> DeploymentORM:
    db_session.expire_all()
    return db_session.get(DeploymentORM, _reconcile.deployment_id)


@pytest.fixture
def ready(db_session) -> DeploymentORM:
    """A deployment its first reconcile made `ready`, with no open job."""
    _reconcile.deployment_id = _seed_deployment(db_session)
    _reconcile(db_session)
    _close_jobs(db_session)
    deployment = _deployment(db_session)
    assert deployment.status == "ready"
    return deployment


def _close_jobs(db_session) -> None:
    for job in db_session.exec(select(DeploymentReconcileJobORM)).all():
        job.status = "done"
        db_session.add(job)
    db_session.commit()


def _request(db_session, state: str) -> DeploymentPowerORM:
    """What the power service writes, minus the enqueue."""
    deployment = _deployment(db_session)
    row = DeploymentPowerORM(deployment_id=deployment.id, state=state, reason="manual")
    db_session.add(row)
    db_session.flush()
    deployment.desired_power_id = row.id
    db_session.add(deployment)
    db_session.commit()
    return row


def _update(db_session) -> None:
    deployment = _deployment(db_session)
    deployment_service.update_deployment(
        db_session,
        DeploymentUpdate(
            id=deployment.id,
            user_id=deployment.user_id,
            desired_template_id=deployment.desired_template_id,
            user_values_json={"user": {"message": "again", "domain": "reconcile.example.test"}},
        ),
    )
    _close_jobs(db_session)


def _helm(provisioner) -> list[dict]:
    return [kw for name, kw in provisioner.calls if name == "helm_upgrade_install"]


def _swept(provisioner) -> bool:
    return any(name == "sweep_stopped_workloads" for name, _ in provisioner.calls)


def _release_columns(db_session, release_id) -> tuple:
    db_session.expire_all()
    r = db_session.get(DeploymentReleaseORM, release_id)
    return (r.started_at, r.ended_at, r.error, r.helm_revision)


def _release_count(db_session) -> int:
    return len(db_session.exec(select(DeploymentReleaseORM)).all())


def _row(db_session, row_id) -> DeploymentPowerORM:
    db_session.expire_all()
    return db_session.get(DeploymentPowerORM, row_id)


def _stop_and_apply(db_session) -> DeploymentPowerORM:
    stop = _request(db_session, "stopped")
    _reconcile(db_session)
    _close_jobs(db_session)
    return stop


def test_stop_then_start(db_session, ready):
    release_id = ready.applied_release_id
    before = _release_columns(db_session, release_id)
    releases = _release_count(db_session)

    stop = _request(db_session, "stopped")
    provisioner = _reconcile(db_session)
    [helm] = _helm(provisioner)
    assert helm["render"] == "stopped"
    assert helm["parking_host"] == "caelus-api.caelus.svc.cluster.local"
    assert helm["parking_port"] == 8000
    assert _swept(provisioner)
    deployment = _deployment(db_session)
    assert (deployment.status, deployment.applied_power_id) == ("ready", stop.id)
    row = _row(db_session, stop.id)
    assert row.started_at is not None and row.ended_at is not None and row.error is None

    start = _request(db_session, "running")
    provisioner = _reconcile(db_session)
    [helm] = _helm(provisioner)
    assert helm["render"] == "normal"
    assert not _swept(provisioner)
    assert _deployment(db_session).applied_power_id == start.id

    # Neither was a rollout.
    assert _release_columns(db_session, release_id) == before
    assert _release_count(db_session) == releases
    assert _deployment(db_session).applied_release_id == release_id


def test_a_failed_stop_reverts_desired_and_touches_no_release(db_session, ready):
    release_id = ready.applied_release_id
    before = _release_columns(db_session, release_id)
    stop = _request(db_session, "stopped")
    provisioner = FakeProvisioner()
    provisioner.raise_on_upgrade = RuntimeError("timed out waiting for the condition")
    _reconcile(db_session, provisioner)

    deployment = _deployment(db_session)
    assert deployment.status == "error"
    assert "timed out" in deployment.last_error
    assert deployment.applied_power_id is None
    assert deployment.desired_power_id is None
    row = _row(db_session, stop.id)
    assert row.ended_at is not None and "timed out" in row.error
    assert _release_columns(db_session, release_id) == before


def test_a_deploy_after_a_failed_stop_renders_normal(db_session, ready):
    stop = _request(db_session, "stopped")
    failing = FakeProvisioner()
    failing.raise_on_upgrade = RuntimeError("boom")
    _reconcile(db_session, failing)
    _close_jobs(db_session)
    failed = _row(db_session, stop.id)
    outcome = (failed.ended_at, failed.error)

    _update(db_session)
    provisioner = _reconcile(db_session)
    [helm] = _helm(provisioner)
    assert helm["render"] == "normal"
    deployment = _deployment(db_session)
    assert deployment.status == "ready"
    assert deployment.power.desired == deployment.power.applied == "running"
    row = _row(db_session, stop.id)
    assert (row.ended_at, row.error) == outcome


def test_a_deploy_after_a_failed_start_stays_stopped(db_session, ready):
    stop = _stop_and_apply(db_session)
    _request(db_session, "running")
    failing = FakeProvisioner()
    failing.raise_on_upgrade = RuntimeError("crash loop")
    _reconcile(db_session, failing)
    _close_jobs(db_session)
    deployment = _deployment(db_session)
    assert (deployment.status, deployment.desired_power_id, deployment.applied_power_id) == ("error", stop.id, stop.id)

    _update(db_session)
    provisioner = _reconcile(db_session)
    [helm] = _helm(provisioner)
    assert helm["render"] == "stopped"
    deployment = _deployment(db_session)
    assert deployment.status == "ready"
    assert deployment.power.desired == deployment.power.applied == "stopped"


def test_an_update_to_a_stopped_deployment_is_a_stopped_rollout(db_session, ready):
    stop = _stop_and_apply(db_session)
    stop_outcome = (_row(db_session, stop.id).started_at, _row(db_session, stop.id).ended_at)
    releases = _release_count(db_session)

    _update(db_session)
    provisioner = _reconcile(db_session)
    [helm] = _helm(provisioner)
    assert helm["render"] == "stopped"
    assert _swept(provisioner)
    deployment = _deployment(db_session)
    assert _release_count(db_session) == releases + 1
    assert deployment.applied_release_id == deployment.desired_release_id
    release = db_session.get(DeploymentReleaseORM, deployment.applied_release_id)
    assert release.ended_at is not None and release.error is None
    # Already stopped: the power row is left as it was.
    assert (_row(db_session, stop.id).started_at, _row(db_session, stop.id).ended_at) == stop_outcome


def test_a_release_and_a_power_change_apply_in_one_helm_run(db_session, ready):
    _update(db_session)
    stop = _request(db_session, "stopped")
    provisioner = _reconcile(db_session)
    [helm] = _helm(provisioner)
    assert helm["render"] == "stopped"
    deployment = _deployment(db_session)
    assert deployment.applied_release_id == deployment.desired_release_id
    release = db_session.get(DeploymentReleaseORM, deployment.applied_release_id)
    assert release.ended_at is not None and release.error is None
    assert deployment.applied_power_id == stop.id
    assert _row(db_session, stop.id).ended_at is not None


class _KilledMidHelm(FakeProvisioner):
    def helm_upgrade_install(self, **kwargs):
        raise KeyboardInterrupt("worker killed")


def test_a_reclaimed_power_reconcile_keeps_its_first_start(db_session, ready):
    stop = _request(db_session, "stopped")
    with pytest.raises(KeyboardInterrupt):
        _reconcile(db_session, _KilledMidHelm())
    db_session.rollback()
    first = _row(db_session, stop.id)
    assert first.started_at is not None and first.ended_at is None
    started = first.started_at

    _reconcile(db_session)
    row = _row(db_session, stop.id)
    assert row.started_at == started
    assert row.ended_at is not None
    assert _deployment(db_session).applied_power_id == stop.id


def test_a_failed_sweep_fails_the_reconcile(db_session, ready):
    stop = _request(db_session, "stopped")
    provisioner = FakeProvisioner()
    provisioner.raise_on_sweep = RuntimeError("Failed to scale deployment/web to 0")
    _reconcile(db_session, provisioner)
    deployment = _deployment(db_session)
    assert deployment.status == "error"
    assert "scale" in deployment.last_error
    assert deployment.applied_power_id is None
    assert "scale" in _row(db_session, stop.id).error


def test_the_recorded_storage_class_reaches_every_helm_run(db_session, ready):
    deployment = _deployment(db_session)
    deployment.storage_class = "ceph-freepod"
    db_session.add(deployment)
    db_session.commit()

    _update(db_session)
    [normal] = _helm(_reconcile(db_session))
    assert normal["storage_class"] == "ceph-freepod"

    _request(db_session, "stopped")
    [stopped] = _helm(_reconcile(db_session))
    assert stopped["render"] == "stopped"
    assert stopped["storage_class"] == "ceph-freepod"


def test_a_deployment_without_a_class_passes_none(db_session, ready):
    _update(db_session)
    [helm] = _helm(_reconcile(db_session))
    assert helm["storage_class"] is None
