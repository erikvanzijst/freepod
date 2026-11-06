"""Stopping and starting a deployment (deployment-power-api).

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
    DEPLOYMENT_STATUS_READY,
    JOB_REASON_POWER,
    POWER_REASON_MANUAL,
    POWER_STATE_RUNNING,
    POWER_STATE_STOPPED,
)

logger = logging.getLogger(__name__)

CODE_DEPLOYMENT_NOT_READY = "deployment_not_ready"
CODE_NOT_STARTABLE = "not_startable"


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


def _locked_deployment(session: Session, *, user_id: int, deployment_id: UUID) -> DeploymentORM:
    # Lock by id alone: the entity query outer-joins its pointers, and
    # Postgres cannot lock the nullable side of an outer join.
    locked = session.exec(
        select(DeploymentORM.id)
        .where(DeploymentORM.id == deployment_id, DeploymentORM.user_id == user_id)
        .with_for_update()
    ).one_or_none()
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

        row = DeploymentPowerORM(
            deployment_id=deployment.id,
            state=target,
            reason=POWER_REASON_MANUAL,
            actor_user_id=actor_user_id,
        )
        session.add(row)
        session.flush()
        deployment.desired_power_id = row.id
        session.add(deployment)
        JobService(session).enqueue_job(deployment_id=deployment.id, reason=JOB_REASON_POWER)
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
