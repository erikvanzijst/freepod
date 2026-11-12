"""Stopping and starting a deployment (deployment-power-api), and holding it
stopped for maintenance (migrate-deployment-storage).

Each request records a power row and moves `desired_power_id` in one
transaction with the reconcile it enqueues; the reconciler applies it.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlmodel import Session, select

from app.models import DeploymentORM, DeploymentRead
from app.models.core import DeploymentPowerORM
from app.services.errors import ConflictException, DeploymentInProgressException, NotFoundException
from app.services.jobs import JobService
from app.services.reconcile_constants import (
    DEPLOYMENT_STATUS_DELETED,
    DEPLOYMENT_STATUS_ERROR,
    DEPLOYMENT_STATUS_READY,
    JOB_REASON_POWER,
    POWER_REASON_MAINTENANCE,
    POWER_REASON_MANUAL,
    POWER_STATE_RUNNING,
    POWER_STATE_STOPPED,
)

logger = logging.getLogger(__name__)

CODE_DEPLOYMENT_NOT_READY = "deployment_not_ready"
CODE_NOT_STARTABLE = "not_startable"
CODE_UNDER_MAINTENANCE = "under_maintenance"


def under_maintenance(deployment: DeploymentORM) -> bool:
    desired = deployment.desired_power
    return desired is not None and desired.reason == POWER_REASON_MAINTENANCE


def refuse_under_maintenance(deployment: DeploymentORM, action: str) -> None:
    if under_maintenance(deployment):
        raise ConflictException(
            f"Deployment is under maintenance and cannot be {action}; try again later",
            code=CODE_UNDER_MAINTENANCE,
        )


def stop_deployment(
    session: Session, *, user_id: int, deployment_id: UUID, actor_user_id: int | None
) -> DeploymentRead:
    return _change_power(
        session,
        user_id=user_id,
        deployment_id=deployment_id,
        actor_user_id=actor_user_id,
        target=POWER_STATE_STOPPED,
    )


def start_deployment(
    session: Session, *, user_id: int, deployment_id: UUID, actor_user_id: int | None
) -> DeploymentRead:
    return _change_power(
        session,
        user_id=user_id,
        deployment_id=deployment_id,
        actor_user_id=actor_user_id,
        target=POWER_STATE_RUNNING,
    )


def begin_maintenance(session: Session, *, deployment_id: UUID) -> DeploymentRead:
    """Stop a ready deployment for the platform, whatever its power, so that
    neither its owner nor an administrator can start or update it until
    `end_maintenance`. Repeating it while it lasts changes nothing."""
    try:
        deployment = _locked_deployment(session, deployment_id=deployment_id)
        if under_maintenance(deployment):
            session.rollback()
            return _read(session, deployment_id)
        if deployment.status != DEPLOYMENT_STATUS_READY:
            raise ConflictException(
                f"Deployment is {deployment.status}; only a ready deployment can enter maintenance",
                code=CODE_DEPLOYMENT_NOT_READY,
            )
        _record(session, deployment, state=POWER_STATE_STOPPED, reason=POWER_REASON_MAINTENANCE)
        session.commit()
    except Exception:
        session.rollback()
        raise
    logger.info("Began maintenance for deployment_id=%s", deployment_id)
    return _read(session, deployment_id)


def end_maintenance(session: Session, *, deployment_id: UUID) -> DeploymentRead:
    """Return a deployment under maintenance to the power it last had applied
    outside maintenance, running when it never had any. Also accepted for a
    failed deployment, which nobody else can change while it is held."""
    try:
        deployment = _locked_deployment(session, deployment_id=deployment_id)
        if not under_maintenance(deployment):
            session.rollback()
            return _read(session, deployment_id)
        if deployment.status not in (DEPLOYMENT_STATUS_READY, DEPLOYMENT_STATUS_ERROR):
            raise ConflictException(
                f"Deployment is {deployment.status}; maintenance can end only once it is ready or failed",
                code=CODE_DEPLOYMENT_NOT_READY,
            )
        before = _power_before_maintenance(session, deployment_id)
        _record(
            session,
            deployment,
            state=before.state if before is not None else POWER_STATE_RUNNING,
            reason=before.reason if before is not None else POWER_REASON_MANUAL,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    logger.info("Ended maintenance for deployment_id=%s", deployment_id)
    return _read(session, deployment_id)


def _power_before_maintenance(session: Session, deployment_id: UUID) -> DeploymentPowerORM | None:
    return session.exec(
        select(DeploymentPowerORM)
        .where(
            DeploymentPowerORM.deployment_id == deployment_id,
            DeploymentPowerORM.reason != POWER_REASON_MAINTENANCE,
            DeploymentPowerORM.ended_at.is_not(None),
            DeploymentPowerORM.error.is_(None),
        )
        .order_by(DeploymentPowerORM.id.desc())
        .limit(1)
    ).one_or_none()


def _record(
    session: Session,
    deployment: DeploymentORM,
    *,
    state: str,
    reason: str,
    actor_user_id: int | None = None,
) -> None:
    row = DeploymentPowerORM(
        deployment_id=deployment.id, state=state, reason=reason, actor_user_id=actor_user_id
    )
    session.add(row)
    session.flush()
    deployment.desired_power_id = row.id
    session.add(deployment)
    JobService(session).enqueue_job(deployment_id=deployment.id, reason=JOB_REASON_POWER)


def _locked_deployment(
    session: Session, *, deployment_id: UUID, user_id: int | None = None
) -> DeploymentORM:
    # Lock by id alone: the entity query outer-joins its pointers, and
    # Postgres cannot lock the nullable side of an outer join.
    query = select(DeploymentORM.id).where(DeploymentORM.id == deployment_id)
    if user_id is not None:
        query = query.where(DeploymentORM.user_id == user_id)
    locked = session.exec(query.with_for_update()).one_or_none()
    if locked is None:
        raise NotFoundException("Deployment not found")
    deployment = session.exec(
        select(DeploymentORM)
        .where(DeploymentORM.id == deployment_id)
        .execution_options(populate_existing=True)
    ).one()
    if deployment.status == DEPLOYMENT_STATUS_DELETED:
        raise NotFoundException("Deployment not found")
    return deployment


def _change_power(
    session: Session,
    *,
    user_id: int,
    deployment_id: UUID,
    actor_user_id: int | None,
    target: str,
) -> DeploymentRead:
    try:
        deployment = _locked_deployment(session, user_id=user_id, deployment_id=deployment_id)
        desired = deployment.desired_power
        desired_state = desired.state if desired is not None else POWER_STATE_RUNNING
        if desired_state == target:
            session.rollback()
            return _read(session, deployment_id)
        if target == POWER_STATE_RUNNING:
            refuse_under_maintenance(deployment, "started")
        if deployment.status != DEPLOYMENT_STATUS_READY:
            raise ConflictException(
                f"Deployment is {deployment.status}; only a ready deployment can be "
                f"{'stopped' if target == POWER_STATE_STOPPED else 'started'}",
                code=CODE_DEPLOYMENT_NOT_READY,
            )
        if target == POWER_STATE_RUNNING and desired is not None and desired.reason != POWER_REASON_MANUAL:
            raise ConflictException(
                f"Deployment is stopped for {desired.reason} and cannot be started",
                code=CODE_NOT_STARTABLE,
            )

        _record(session, deployment, state=target, reason=POWER_REASON_MANUAL, actor_user_id=actor_user_id)
        session.commit()
    except DeploymentInProgressException:
        session.rollback()
        logger.warning("Power change blocked by in-progress reconcile job deployment_id=%s", deployment_id)
        raise
    except Exception:
        session.rollback()
        raise
    logger.info(
        "Requested power=%s for deployment_id=%s user_id=%s actor_user_id=%s",
        target, deployment_id, user_id, actor_user_id,
    )
    return _read(session, deployment_id)


def _read(session: Session, deployment_id: UUID) -> DeploymentRead:
    from app.services.deployments import get_deployment

    session.expire_all()
    return get_deployment(session, deployment_id=deployment_id)
