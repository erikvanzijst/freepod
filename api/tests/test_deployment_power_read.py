"""Deployment reads report power from the database alone
(deployment-power-data-model)."""

from __future__ import annotations

import subprocess

import pytest
from sqlalchemy import event

from app.models import DeploymentORM
from app.models.core import DeploymentPowerORM
from app.services import deployments as deployment_service
from tests.conftest import ADMIN_EMAIL, make_bare_deployment


def _admin_id(db_session) -> int:
    from app.models import UserORM
    from sqlmodel import select

    return db_session.exec(select(UserORM).where(UserORM.email == ADMIN_EMAIL)).one().id


def _power(db_session, deployment: DeploymentORM, state: str, reason: str = "manual") -> DeploymentPowerORM:
    row = DeploymentPowerORM(deployment_id=deployment.id, state=state, reason=reason)
    db_session.add(row)
    db_session.flush()
    return row


def _set(db_session, deployment, *, desired=None, applied=None) -> None:
    deployment.desired_power_id = desired.id if desired is not None else None
    deployment.applied_power_id = applied.id if applied is not None else None
    db_session.add(deployment)
    db_session.commit()


def _read(client, deployment) -> dict:
    resp = client.get(f"/api/users/{deployment.user_id}/deployments/{deployment.id}")
    assert resp.status_code == 200, resp.text
    return resp.json()["power"]


def test_a_never_stopped_deployment_reads_running(client, db_session):
    deployment = make_bare_deployment(db_session, _admin_id(db_session))
    assert _read(client, deployment) == {"desired": "running", "applied": "running", "reason": None}


def test_a_stopping_deployment(client, db_session):
    deployment = make_bare_deployment(db_session, _admin_id(db_session))
    stop = _power(db_session, deployment, "stopped")
    _set(db_session, deployment, desired=stop)
    assert _read(client, deployment) == {"desired": "stopped", "applied": "running", "reason": "manual"}


def test_a_stopped_deployment(client, db_session):
    deployment = make_bare_deployment(db_session, _admin_id(db_session))
    stop = _power(db_session, deployment, "stopped", reason="payment")
    _set(db_session, deployment, desired=stop, applied=stop)
    assert _read(client, deployment) == {"desired": "stopped", "applied": "stopped", "reason": "payment"}


def test_a_starting_deployment_has_no_reason(client, db_session):
    deployment = make_bare_deployment(db_session, _admin_id(db_session))
    stop = _power(db_session, deployment, "stopped")
    start = _power(db_session, deployment, "running")
    _set(db_session, deployment, desired=start, applied=stop)
    assert _read(client, deployment) == {"desired": "running", "applied": "stopped", "reason": None}


@pytest.fixture
def no_kubectl(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError(f"a deployment read ran a command: {args!r}")

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)


def _statements_listing(db_session, user_id: int) -> tuple[list[str], list]:
    statements: list[str] = []

    def record(conn, cursor, statement, *args):
        statements.append(statement)

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        db_session.expire_all()
        reads = deployment_service.list_deployments(db_session, user_id=user_id)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return statements, reads


def test_listing_reads_power_without_a_query_per_deployment(db_session, client, no_kubectl):
    user_id = _admin_id(db_session)
    first = make_bare_deployment(db_session, user_id)
    single, _ = _statements_listing(db_session, user_id)

    for state in ("stopped", "running"):
        deployment = make_bare_deployment(db_session, user_id)
        row = _power(db_session, deployment, state)
        _set(db_session, deployment, desired=row, applied=row)
    stop = _power(db_session, first, "stopped")
    _set(db_session, first, desired=stop)

    many, reads = _statements_listing(db_session, user_id)
    assert len(many) == len(single)
    assert "deployment_power" in many[0]
    assert sorted((r.power.desired, r.power.applied) for r in reads) == [
        ("running", "running"),
        ("stopped", "running"),
        ("stopped", "stopped"),
    ]


def test_power_rows_are_removed_with_their_deployment(db_session, client):
    from sqlalchemy import delete, func, select

    deployment = make_bare_deployment(db_session, _admin_id(db_session))
    stop = _power(db_session, deployment, "stopped")
    _set(db_session, deployment, desired=stop, applied=stop)
    deployment_id = deployment.id

    db_session.execute(delete(DeploymentORM).where(DeploymentORM.id == deployment_id))
    db_session.commit()
    remaining = db_session.execute(
        select(func.count()).select_from(DeploymentPowerORM).where(DeploymentPowerORM.deployment_id == deployment_id)
    ).scalar()
    assert remaining == 0
