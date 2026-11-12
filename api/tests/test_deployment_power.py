"""Stopping and starting a deployment through the service, REST and `caelus`
(deployment-power-api)."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.models import DeploymentORM, DeploymentUpdate, UserORM
from app.models.core import DeploymentPowerORM, DeploymentReconcileJobORM
from app.services import deployments as deployment_service
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


# ── Maintenance ──────────────────────────────────────────────────────────


def _hold(db_session, deployment) -> None:
    power.begin_maintenance(db_session, deployment_id=deployment.id)
    _apply(db_session, deployment)


def _update(db_session, deployment):
    return deployment_service.update_deployment(
        db_session,
        DeploymentUpdate(
            id=deployment.id, user_id=deployment.user_id, desired_template_id=deployment.desired_template_id
        ),
    )


def test_maintenance_stops_for_the_platform(db_session, owned):
    deployment, _ = owned
    read = power.begin_maintenance(db_session, deployment_id=deployment.id)
    assert (read.power.desired, read.power.applied, read.power.reason) == ("stopped", "running", "maintenance")
    [row] = _rows(db_session, deployment.id)
    assert (row.state, row.reason, row.actor_user_id) == ("stopped", "maintenance", None)
    assert [j.reason for j in _jobs(db_session, deployment.id)] == [JOB_REASON_POWER]


def test_maintenance_twice_records_nothing(db_session, owned):
    deployment, _ = owned
    _hold(db_session, deployment)
    power.begin_maintenance(db_session, deployment_id=deployment.id)
    assert len(_rows(db_session, deployment.id)) == 1
    assert all(j.status == "done" for j in _jobs(db_session, deployment.id))


@pytest.mark.parametrize("status", ["error", "provisioning", "pending", "deleting"])
def test_maintenance_requires_ready(client, db_session, status):
    owner = create_user(client, OWNER)
    deployment = make_bare_deployment(db_session, owner["id"], status=status)
    with pytest.raises(ConflictException) as exc:
        power.begin_maintenance(db_session, deployment_id=deployment.id)
    assert exc.value.code == "deployment_not_ready"
    assert _rows(db_session, deployment.id) == []


def test_maintenance_waits_for_an_open_reconcile(db_session, owned):
    deployment, _ = owned
    JobService(db_session).enqueue_job(deployment_id=deployment.id, reason=JOB_REASON_UPDATE)
    db_session.commit()
    with pytest.raises(DeploymentInProgressException):
        power.begin_maintenance(db_session, deployment_id=deployment.id)
    assert _rows(db_session, deployment.id) == []


def test_the_owner_cannot_start_a_deployment_under_maintenance(db_session, owned):
    deployment, owner = owned
    _hold(db_session, deployment)
    with pytest.raises(ConflictException) as exc:
        power.start_deployment(db_session, user_id=owner["id"], deployment_id=deployment.id, actor_user_id=None)
    assert exc.value.code == "under_maintenance"
    assert len(_rows(db_session, deployment.id)) == 1


def test_maintenance_outranks_a_failed_status_on_start(db_session, owned):
    deployment, owner = owned
    _hold(db_session, deployment)
    row = db_session.get(DeploymentORM, deployment.id)
    row.status = "error"
    db_session.add(row)
    db_session.commit()
    with pytest.raises(ConflictException) as exc:
        power.start_deployment(db_session, user_id=owner["id"], deployment_id=deployment.id, actor_user_id=None)
    assert exc.value.code == "under_maintenance"


def test_stopping_a_deployment_under_maintenance_records_nothing(db_session, owned):
    deployment, owner = owned
    _hold(db_session, deployment)
    read = power.stop_deployment(db_session, user_id=owner["id"], deployment_id=deployment.id, actor_user_id=None)
    assert read.power.reason == "maintenance"
    assert len(_rows(db_session, deployment.id)) == 1


def test_a_deployment_under_maintenance_cannot_be_updated(db_session, owned):
    deployment, _ = owned
    _hold(db_session, deployment)
    with pytest.raises(ConflictException) as exc:
        _update(db_session, deployment)
    assert exc.value.code == "under_maintenance"
    row = db_session.get(DeploymentORM, deployment.id)
    assert (row.status, row.desired_release_id) == ("ready", deployment.desired_release_id)
    assert all(j.status == "done" for j in _jobs(db_session, deployment.id))


def test_an_update_is_accepted_again_once_maintenance_ends(db_session, owned):
    deployment, _ = owned
    _hold(db_session, deployment)
    power.end_maintenance(db_session, deployment_id=deployment.id)
    _apply(db_session, deployment)
    assert _update(db_session, deployment).status == "provisioning"


def test_ending_maintenance_restores_running(db_session, owned):
    deployment, _ = owned
    _hold(db_session, deployment)
    read = power.end_maintenance(db_session, deployment_id=deployment.id)
    assert (read.power.desired, read.power.applied, read.power.reason) == ("running", "stopped", None)
    _, restored = _rows(db_session, deployment.id)
    assert (restored.state, restored.reason, restored.actor_user_id) == ("running", "manual", None)


@pytest.mark.parametrize("reason", ["manual", "payment"])
def test_ending_maintenance_restores_the_stop_before_it(db_session, owned, reason):
    deployment, _ = owned
    row = DeploymentPowerORM(deployment_id=deployment.id, state="stopped", reason=reason, actor_user_id=None)
    db_session.add(row)
    db_session.flush()
    row.started_at = row.ended_at = row.created_at
    deployment.desired_power_id = deployment.applied_power_id = row.id
    db_session.add_all([row, deployment])
    db_session.commit()
    _hold(db_session, deployment)
    read = power.end_maintenance(db_session, deployment_id=deployment.id)
    assert (read.power.desired, read.power.reason) == ("stopped", reason)
    assert [r.reason for r in _rows(db_session, deployment.id)] == [reason, "maintenance", reason]


def test_ending_maintenance_skips_failed_and_superseded_rows(db_session, owned):
    deployment, owner = owned
    power.stop_deployment(db_session, user_id=owner["id"], deployment_id=deployment.id, actor_user_id=None)
    _apply(db_session, deployment)
    stopped = _rows(db_session, deployment.id)[-1]
    stopped.started_at = stopped.ended_at = stopped.created_at
    failed = DeploymentPowerORM(
        deployment_id=deployment.id, state="running", reason="manual", error="boom",
        started_at=stopped.created_at, ended_at=stopped.created_at,
    )
    never = DeploymentPowerORM(deployment_id=deployment.id, state="running", reason="manual")
    db_session.add_all([stopped, failed, never])
    db_session.commit()
    _hold(db_session, deployment)
    read = power.end_maintenance(db_session, deployment_id=deployment.id)
    assert (read.power.desired, read.power.reason) == ("stopped", "manual")


def test_ending_maintenance_is_accepted_for_a_failed_deployment(db_session, owned):
    deployment, _ = owned
    _hold(db_session, deployment)
    row = db_session.get(DeploymentORM, deployment.id)
    row.status = "error"
    db_session.add(row)
    db_session.commit()
    assert power.end_maintenance(db_session, deployment_id=deployment.id).power.desired == "running"


def test_ending_maintenance_when_there_is_none_records_nothing(db_session, owned):
    deployment, _ = owned
    power.end_maintenance(db_session, deployment_id=deployment.id)
    assert _rows(db_session, deployment.id) == []
    assert _jobs(db_session, deployment.id) == []


def test_maintenance_twice_restores_what_preceded_the_first(db_session, owned):
    deployment, owner = owned
    power.stop_deployment(db_session, user_id=owner["id"], deployment_id=deployment.id, actor_user_id=None)
    _apply(db_session, deployment)
    _rows(db_session, deployment.id)[-1].ended_at = _rows(db_session, deployment.id)[-1].created_at
    db_session.commit()
    for _ in range(2):
        _hold(db_session, deployment)
        power.end_maintenance(db_session, deployment_id=deployment.id)
        _apply(db_session, deployment)
        last = _rows(db_session, deployment.id)[-1]
        last.ended_at = last.created_at
        db_session.commit()
    assert [r.reason for r in _rows(db_session, deployment.id)] == [
        "manual", "maintenance", "manual", "maintenance", "manual",
    ]
    assert _rows(db_session, deployment.id)[-1].state == "stopped"


@pytest.mark.parametrize("reason, accepted", [("maintenance", True), ("bogus", False)])
def test_the_database_holds_the_reason_set(db_session, owned, reason, accepted):
    deployment, _ = owned
    db_session.add(DeploymentPowerORM(deployment_id=deployment.id, state="stopped", reason=reason))
    if accepted:
        db_session.commit()
        return
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_rest_refuses_start_and_update_under_maintenance(client, db_session, owned):
    deployment, _ = owned
    _hold(db_session, deployment)
    resp = client.post(_url(deployment, "start"), headers=auth_header(OWNER))
    assert (resp.status_code, resp.json().get("code")) == (409, "under_maintenance")
    resp = client.put(
        f"/api/users/{deployment.user_id}/deployments/{deployment.id}",
        json={"desired_template_id": deployment.desired_template_id},
        headers=auth_header(OWNER),
    )
    assert (resp.status_code, resp.json().get("code")) == (409, "under_maintenance")


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
