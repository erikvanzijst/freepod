"""Stopping and starting a deployment through the service, REST and `caelus`
(deployment-power-api)."""

from __future__ import annotations

import pytest
from sqlmodel import select

from app.models import DeploymentORM, UserORM
from app.models.core import DeploymentPowerORM, DeploymentReconcileJobORM
from app.services import power
from app.services.errors import ConflictException, DeploymentInProgressException, NotFoundException
from app.services.jobs import JobService
from app.services.reconcile_constants import JOB_REASON_POWER, JOB_REASON_UPDATE
from tests.conftest import ADMIN_EMAIL, auth_header, create_user, make_bare_deployment

OWNER = "owner@example.com"
OTHER = "other@example.com"


def _rows(db_session, deployment_id) -> list[DeploymentPowerORM]:
    db_session.expire_all()
    return list(
        db_session.exec(
            select(DeploymentPowerORM)
            .where(DeploymentPowerORM.deployment_id == deployment_id)
            .order_by(DeploymentPowerORM.id)
        ).all()
    )


def _jobs(db_session, deployment_id) -> list[DeploymentReconcileJobORM]:
    db_session.expire_all()
    return list(
        db_session.exec(
            select(DeploymentReconcileJobORM).where(DeploymentReconcileJobORM.deployment_id == deployment_id)
        ).all()
    )


def _finish_jobs(db_session, deployment_id) -> None:
    for job in _jobs(db_session, deployment_id):
        job.status = "done"
        db_session.add(job)
    db_session.commit()


def _apply(db_session, deployment) -> None:
    """What a successful power reconcile leaves behind."""
    db_session.expire_all()
    row = db_session.get(DeploymentORM, deployment.id)
    row.applied_power_id = row.desired_power_id
    db_session.add(row)
    db_session.commit()
    _finish_jobs(db_session, deployment.id)


def _admin(db_session) -> UserORM:
    return db_session.exec(select(UserORM).where(UserORM.email == ADMIN_EMAIL)).one()


@pytest.fixture
def owned(client, db_session):
    owner = create_user(client, OWNER)
    return make_bare_deployment(db_session, owner["id"]), owner


def _url(deployment, action: str) -> str:
    return f"/api/users/{deployment.user_id}/deployments/{deployment.id}/{action}"


# ── Service ──────────────────────────────────────────────────────────────


def test_stopping_records_a_row_moves_desired_and_enqueues(db_session, owned):
    deployment, owner = owned
    read = power.stop_deployment(
        db_session, user_id=owner["id"], deployment_id=deployment.id, actor_user_id=owner["id"]
    )
    assert (read.power.desired, read.power.applied, read.power.reason) == ("stopped", "running", "manual")
    [row] = _rows(db_session, deployment.id)
    assert (row.state, row.reason, row.actor_user_id) == ("stopped", "manual", owner["id"])
    assert row.started_at is None and row.ended_at is None
    assert db_session.get(DeploymentORM, deployment.id).desired_power_id == row.id
    assert db_session.get(DeploymentORM, deployment.id).applied_power_id is None
    assert [j.reason for j in _jobs(db_session, deployment.id)] == [JOB_REASON_POWER]


def test_starting_records_a_further_row(db_session, owned):
    deployment, owner = owned
    power.stop_deployment(db_session, user_id=owner["id"], deployment_id=deployment.id, actor_user_id=None)
    _apply(db_session, deployment)
    read = power.start_deployment(db_session, user_id=owner["id"], deployment_id=deployment.id, actor_user_id=None)
    assert (read.power.desired, read.power.applied, read.power.reason) == ("running", "stopped", None)
    first, second = _rows(db_session, deployment.id)
    assert (first.state, second.state) == ("stopped", "running")
    assert second.reason == "manual"


@pytest.mark.parametrize("applied", [False, True], ids=["stopping", "stopped"])
def test_stopping_twice_records_nothing(db_session, owned, applied):
    deployment, owner = owned
    power.stop_deployment(db_session, user_id=owner["id"], deployment_id=deployment.id, actor_user_id=None)
    if applied:
        _apply(db_session, deployment)
    jobs_before = len(_jobs(db_session, deployment.id))
    read = power.stop_deployment(db_session, user_id=owner["id"], deployment_id=deployment.id, actor_user_id=None)
    assert read.power.desired == "stopped"
    assert len(_rows(db_session, deployment.id)) == 1
    assert len(_jobs(db_session, deployment.id)) == jobs_before


def test_starting_a_running_deployment_records_nothing(db_session, owned):
    deployment, owner = owned
    read = power.start_deployment(db_session, user_id=owner["id"], deployment_id=deployment.id, actor_user_id=None)
    assert (read.power.desired, read.power.applied) == ("running", "running")
    assert _rows(db_session, deployment.id) == []
    assert _jobs(db_session, deployment.id) == []


@pytest.mark.parametrize("status", ["error", "provisioning", "pending", "deleting"])
@pytest.mark.parametrize("change", [power.stop_deployment, power.start_deployment], ids=["stop", "start"])
def test_power_changes_require_ready(client, db_session, status, change):
    owner = create_user(client, OWNER)
    deployment = make_bare_deployment(db_session, owner["id"], status=status)
    if change is power.start_deployment:
        row = DeploymentPowerORM(deployment_id=deployment.id, state="stopped", reason="manual")
        db_session.add(row)
        db_session.flush()
        deployment.desired_power_id = deployment.applied_power_id = row.id
        db_session.add(deployment)
        db_session.commit()
    before = len(_rows(db_session, deployment.id))
    with pytest.raises(ConflictException) as exc:
        change(db_session, user_id=owner["id"], deployment_id=deployment.id, actor_user_id=None)
    assert exc.value.code == "deployment_not_ready"
    assert len(_rows(db_session, deployment.id)) == before
    assert _jobs(db_session, deployment.id) == []


def test_a_payment_stop_cannot_be_started(db_session, owned):
    deployment, owner = owned
    row = DeploymentPowerORM(deployment_id=deployment.id, state="stopped", reason="payment")
    db_session.add(row)
    db_session.flush()
    deployment.desired_power_id = deployment.applied_power_id = row.id
    db_session.add(deployment)
    db_session.commit()
    with pytest.raises(ConflictException) as exc:
        power.start_deployment(db_session, user_id=owner["id"], deployment_id=deployment.id, actor_user_id=None)
    assert exc.value.code == "not_startable"
    assert len(_rows(db_session, deployment.id)) == 1


@pytest.mark.parametrize("change", [power.stop_deployment, power.start_deployment], ids=["stop", "start"])
def test_an_open_reconcile_refuses_and_records_nothing(db_session, owned, change):
    deployment, owner = owned
    if change is power.start_deployment:
        power.stop_deployment(db_session, user_id=owner["id"], deployment_id=deployment.id, actor_user_id=None)
        _apply(db_session, deployment)
    before = len(_rows(db_session, deployment.id))
    JobService(db_session).enqueue_job(deployment_id=deployment.id, reason=JOB_REASON_UPDATE)
    db_session.commit()
    with pytest.raises(DeploymentInProgressException):
        change(db_session, user_id=owner["id"], deployment_id=deployment.id, actor_user_id=None)
    assert len(_rows(db_session, deployment.id)) == before
    deployment_row = db_session.get(DeploymentORM, deployment.id)
    assert deployment_row.desired_power_id == deployment_row.applied_power_id


def test_another_users_deployment_is_not_found(client, db_session, owned):
    deployment, _ = owned
    other = create_user(client, OTHER)
    with pytest.raises(NotFoundException):
        power.stop_deployment(db_session, user_id=other["id"], deployment_id=deployment.id, actor_user_id=None)


# ── REST ─────────────────────────────────────────────────────────────────


def test_the_owner_stops_and_starts(client, db_session, owned):
    deployment, owner = owned
    resp = client.post(_url(deployment, "stop"), headers=auth_header(OWNER))
    assert resp.status_code == 200, resp.text
    assert resp.json()["power"] == {"desired": "stopped", "applied": "running", "reason": "manual"}
    _apply(db_session, deployment)
    resp = client.post(_url(deployment, "start"), headers=auth_header(OWNER))
    assert resp.status_code == 200, resp.text
    assert resp.json()["power"] == {"desired": "running", "applied": "stopped", "reason": None}
    assert [r.actor_user_id for r in _rows(db_session, deployment.id)] == [owner["id"], owner["id"]]


def test_an_administrator_is_recorded_as_actor(client, db_session, owned):
    deployment, _ = owned
    resp = client.post(_url(deployment, "stop"))
    assert resp.status_code == 200, resp.text
    [row] = _rows(db_session, deployment.id)
    assert row.actor_user_id == _admin(db_session).id


@pytest.mark.parametrize("action", ["stop", "start"])
def test_another_user_is_forbidden(client, db_session, owned, action):
    deployment, _ = owned
    create_user(client, OTHER)
    resp = client.post(_url(deployment, action), headers=auth_header(OTHER))
    assert resp.status_code == 403
    assert _rows(db_session, deployment.id) == []


@pytest.mark.parametrize("action", ["stop", "start"])
def test_a_missing_deployment_is_404(client, owned, action):
    deployment, owner = owned
    resp = client.post(
        f"/api/users/{owner['id']}/deployments/00000000-0000-0000-0000-000000000000/{action}",
        headers=auth_header(OWNER),
    )
    assert resp.status_code == 404


def test_rest_refusals_carry_their_codes(client, db_session):
    owner = create_user(client, OWNER)
    failed = make_bare_deployment(db_session, owner["id"], status="error")
    resp = client.post(_url(failed, "stop"), headers=auth_header(OWNER))
    assert (resp.status_code, resp.json().get("code")) == (409, "deployment_not_ready")

    paused = make_bare_deployment(db_session, owner["id"])
    row = DeploymentPowerORM(deployment_id=paused.id, state="stopped", reason="payment")
    db_session.add(row)
    db_session.flush()
    paused.desired_power_id = paused.applied_power_id = row.id
    db_session.add(paused)
    db_session.commit()
    resp = client.post(_url(paused, "start"), headers=auth_header(OWNER))
    assert (resp.status_code, resp.json().get("code")) == (409, "not_startable")


def test_rest_in_progress_is_409(client, db_session, owned):
    deployment, _ = owned
    JobService(db_session).enqueue_job(deployment_id=deployment.id, reason=JOB_REASON_UPDATE)
    db_session.commit()
    resp = client.post(_url(deployment, "stop"), headers=auth_header(OWNER))
    assert resp.status_code == 409
    assert "code" not in resp.json()
    assert _rows(db_session, deployment.id) == []


# ── caelus ───────────────────────────────────────────────────────────────


def _caelus(cli_runner, *args):
    runner, cli = cli_runner
    return runner.invoke(cli, list(args))


def test_caelus_stops_and_starts_with_no_actor(cli_runner, client, db_session, owned):
    deployment, owner = owned
    ids = ["--user-id", str(owner["id"]), "--deployment-id", str(deployment.id)]
    result = _caelus(cli_runner, "stop-deployment", *ids)
    assert result.exit_code == 0, result.output
    assert "desired: stopped" in result.output
    _apply(db_session, deployment)
    result = _caelus(cli_runner, "start-deployment", *ids)
    assert result.exit_code == 0, result.output
    rows = _rows(db_session, deployment.id)
    assert [(r.state, r.actor_user_id) for r in rows] == [("stopped", None), ("running", None)]


def test_caelus_gives_the_same_refusal(cli_runner, client, db_session):
    owner = create_user(client, OWNER)
    failed = make_bare_deployment(db_session, owner["id"], status="error")
    row = DeploymentPowerORM(deployment_id=failed.id, state="stopped", reason="manual")
    db_session.add(row)
    db_session.flush()
    failed.desired_power_id = failed.applied_power_id = row.id
    db_session.add(failed)
    db_session.commit()
    result = _caelus(
        cli_runner, "start-deployment", "--user-id", str(owner["id"]), "--deployment-id", str(failed.id)
    )
    assert result.exit_code == 1
    assert "deployment_not_ready" in result.output


def test_caelus_in_progress_fails(cli_runner, client, db_session, owned):
    deployment, owner = owned
    JobService(db_session).enqueue_job(deployment_id=deployment.id, reason=JOB_REASON_UPDATE)
    db_session.commit()
    result = _caelus(
        cli_runner, "stop-deployment", "--user-id", str(owner["id"]), "--deployment-id", str(deployment.id)
    )
    assert result.exit_code == 1
    assert _rows(db_session, deployment.id) == []
