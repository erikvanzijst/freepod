from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Path, Response, status
from sqlmodel import Session

from app.db import get_session
from app.deps import require_self
from app.models import UserORM, VarsRead, VarsWrite
from app.services import deployments as deployment_service
from app.services import vars as vars_service

router = APIRouter(
    prefix="/users/{user_id}/deployments/{deployment_id}/vars",
    tags=["vars"],
)

PHASE_DESCRIPTION = (
    "When the value is consumed. `runtime` is the only phase, and anything "
    "else is 404. Never a deployment environment such as `production` — that "
    "axis is the deployment itself, one segment earlier."
)


def _deployment(
    session: Session,
    *,
    user_id: int,
    deployment_id: UUID,
    phase: str,
    caller: UserORM,
):
    """Resolve the deployment and the phase, or fail the way a read would."""
    vars_service.require_phase(phase)
    return deployment_service.get_deployment_orm(
        session,
        deployment_id=deployment_id,
        user_id=None if caller.is_admin else user_id,
    )


@router.get(
    "/{phase}",
    response_model=VarsRead,
    summary="Read a deployment's vars",
    response_description="The deployment's vars, with sensitive values omitted.",
    responses={
        200: {"description": "The deployment's vars for this phase."},
        403: {"description": "Caller may only read their own deployments' vars."},
        404: {"description": "No such deployment for this user, or unknown phase."},
    },
)
def list_vars(
    user_id: int = Path(..., description="ID of the user that owns the deployment."),
    deployment_id: UUID = Path(..., description="UUID of the deployment."),
    phase: str = Path(..., description=PHASE_DESCRIPTION),
    current_user: UserORM = Depends(require_self),
    session: Session = Depends(get_session),
) -> VarsRead:
    """Read the environment a deployment's pod is configured with.

    ## Authorization
    You may only read your own deployments' vars; administrators may read any
    account's. Other requests receive `403 Forbidden`.

    ## Parameters
    - **user_id** — owner of the deployment.
    - **deployment_id** — UUID of the deployment.
    - **phase** — when the value is consumed. `runtime` is the only phase.

    ## Behavior
    Reports the deployment's *desired* vars, which is not necessarily what the
    running pod holds — `pending` is true when a rollout would change the
    pod's environment.

    A var marked sensitive is returned **without its `value` field**: not a
    mask, not a null, and no digest. The response is therefore safe to modify
    and submit back: an entry with no `value` leaves that var untouched.

    ## Errors
    - **403 Forbidden** — reading another account's vars without administrator
      privileges.
    - **404 Not Found** — no such deployment for this user, or a phase other
      than `runtime`.
    """
    deployment = _deployment(
        session, user_id=user_id, deployment_id=deployment_id, phase=phase, caller=current_user
    )
    return vars_service.read_vars(session, deployment)


@router.patch(
    "/{phase}",
    response_model=VarsRead,
    summary="Merge vars into a deployment",
    response_description="The deployment's vars after the merge.",
    responses={
        200: {"description": "The resulting vars."},
        400: {"description": "A key, value or sensitivity the template does not allow."},
        403: {"description": "Caller may only write their own deployments' vars."},
        404: {"description": "No such deployment for this user, or unknown phase."},
        409: {"description": "The deployment is being deleted."},
    },
)
def merge_vars(
    payload: VarsWrite,
    user_id: int = Path(..., description="ID of the user that owns the deployment."),
    deployment_id: UUID = Path(..., description="UUID of the deployment."),
    phase: str = Path(..., description=PHASE_DESCRIPTION),
    current_user: UserORM = Depends(require_self),
    session: Session = Depends(get_session),
) -> VarsRead:
    """Set, change or delete some of a deployment's vars, leaving the rest.

    ## Authorization
    You may only write your own deployments' vars; administrators may write
    any account's. Other requests receive `403 Forbidden`.

    ## Parameters
    - **user_id** — owner of the deployment.
    - **deployment_id** — UUID of the deployment.
    - **phase** — when the value is consumed. `runtime` is the only phase.

    ## Behavior
    Keys present in the body are written; keys absent from it are untouched.
    Within an entry, `value` has three distinct meanings:

    - a string — set the var to it;
    - `null` — delete the var;
    - **absent** — leave the var's value unchanged, which is what makes a
      read's output safely writable. Naming a key that does not exist this way
      is an error, since there is nothing to leave unchanged.

    Writing does **not** roll the deployment out. The vars are recorded as
    desired state and `pending` reports that a rollout would change the pod.

    Nothing is written unless a value or its sensitivity actually changes, so
    re-submitting a deployment's own configuration records no history.

    ## Errors
    - **400 Bad Request** — a key that is not a legal environment variable
      name or is reserved by the platform, a value the template's schema
      rejects, a value over 8 KiB, vars totalling over 128 KiB or numbering
      over 256, sensitivity contradicting the schema, or making a sensitive
      var readable without supplying a new value. The error names the key and
      the constraint and never quotes the value.
    - **403 Forbidden** — writing another account's vars without administrator
      privileges.
    - **404 Not Found** — no such deployment for this user, or a phase other
      than `runtime`.
    - **409 Conflict** — the deployment is being deleted.
    """
    deployment = _deployment(
        session, user_id=user_id, deployment_id=deployment_id, phase=phase, caller=current_user
    )
    vars_service.assert_writable(deployment)
    vars_service.write_vars(
        session, deployment=deployment, actor=current_user, entries=payload.vars
    )
    session.commit()
    return vars_service.read_vars(session, deployment)


@router.put(
    "/{phase}",
    response_model=VarsRead,
    summary="Replace a deployment's vars",
    response_description="The deployment's vars after the replacement.",
    responses={
        200: {"description": "The resulting vars."},
        400: {"description": "A key, value or sensitivity the template does not allow."},
        403: {"description": "Caller may only write their own deployments' vars."},
        404: {"description": "No such deployment for this user, or unknown phase."},
        409: {"description": "The deployment is being deleted."},
    },
)
def replace_vars(
    payload: VarsWrite,
    user_id: int = Path(..., description="ID of the user that owns the deployment."),
    deployment_id: UUID = Path(..., description="UUID of the deployment."),
    phase: str = Path(..., description=PHASE_DESCRIPTION),
    current_user: UserORM = Depends(require_self),
    session: Session = Depends(get_session),
) -> VarsRead:
    """Make a deployment's vars exactly what the body says.

    ## Authorization
    You may only write your own deployments' vars; administrators may write
    any account's. Other requests receive `403 Forbidden`.

    ## Parameters
    - **user_id** — owner of the deployment.
    - **deployment_id** — UUID of the deployment.
    - **phase** — when the value is consumed. `runtime` is the only phase.

    ## Behavior
    Identical to `PATCH` except that a key **absent** from the body is
    deleted. An entry that omits `value` still means "leave this var's value
    unchanged", so the output of a read can be submitted here to assert the
    deployment's current configuration without needing to know any secret.

    This affects only the phase in the path.

    ## Errors
    As `PATCH`.
    """
    deployment = _deployment(
        session, user_id=user_id, deployment_id=deployment_id, phase=phase, caller=current_user
    )
    vars_service.assert_writable(deployment)
    vars_service.write_vars(
        session,
        deployment=deployment,
        actor=current_user,
        entries=payload.vars,
        replace=True,
    )
    session.commit()
    return vars_service.read_vars(session, deployment)


@router.get(
    "/{phase}/{key}",
    response_model=VarsRead,
    summary="Read one var",
    response_description="The var, in the same shape as the collection.",
    responses={
        200: {"description": "The var."},
        403: {"description": "Caller may only read their own deployments' vars."},
        404: {"description": "No such deployment, phase, or var."},
    },
)
def get_var(
    user_id: int = Path(..., description="ID of the user that owns the deployment."),
    deployment_id: UUID = Path(..., description="UUID of the deployment."),
    phase: str = Path(..., description=PHASE_DESCRIPTION),
    key: str = Path(..., description="The var's name, which is the environment variable's name."),
    current_user: UserORM = Depends(require_self),
    session: Session = Depends(get_session),
) -> VarsRead:
    """Read a single var.

    ## Authorization
    You may only read your own deployments' vars; administrators may read any
    account's. Other requests receive `403 Forbidden`.

    ## Parameters
    - **user_id** — owner of the deployment.
    - **deployment_id** — UUID of the deployment.
    - **phase** — when the value is consumed. `runtime` is the only phase.
    - **key** — the var's name, which is the environment variable's name.

    ## Behavior
    Returns the same envelope the collection returns, holding one entry, so a
    client parses one shape everywhere. A sensitive var carries no `value`.

    ## Errors
    - **403 Forbidden** — reading another account's vars without administrator
      privileges.
    - **404 Not Found** — no such deployment for this user, a phase other than
      `runtime`, or no such var.
    """
    deployment = _deployment(
        session, user_id=user_id, deployment_id=deployment_id, phase=phase, caller=current_user
    )
    return vars_service.read_var(session, deployment, key)


@router.delete(
    "/{phase}/{key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete one var",
    response_description="The var is not in the deployment's configuration.",
    responses={
        204: {"description": "The var is gone, or was never there."},
        403: {"description": "Caller may only write their own deployments' vars."},
        404: {"description": "No such deployment for this user, or unknown phase."},
        409: {"description": "The deployment is being deleted."},
    },
)
def delete_var(
    user_id: int = Path(..., description="ID of the user that owns the deployment."),
    deployment_id: UUID = Path(..., description="UUID of the deployment."),
    phase: str = Path(..., description=PHASE_DESCRIPTION),
    key: str = Path(..., description="The var's name."),
    current_user: UserORM = Depends(require_self),
    session: Session = Depends(get_session),
) -> Response:
    """Remove a var from a deployment's configuration.

    ## Authorization
    You may only write your own deployments' vars; administrators may write
    any account's. Other requests receive `403 Forbidden`.

    ## Parameters
    - **user_id** — owner of the deployment.
    - **deployment_id** — UUID of the deployment.
    - **phase** — when the value is consumed. `runtime` is the only phase.
    - **key** — the var's name, which is the environment variable's name.

    ## Behavior
    Idempotent: deleting a key the deployment does not have succeeds and
    records nothing. Deleting one it does have records a deletion rather than
    erasing the past, so an earlier release's snapshot still resolves to what
    that release shipped.

    The pod keeps the variable until the next rollout; `pending` reports the
    difference.

    ## Errors
    - **403 Forbidden** — writing another account's vars without administrator
      privileges.
    - **404 Not Found** — no such deployment for this user, or a phase other
      than `runtime`.
    - **409 Conflict** — the deployment is being deleted.
    """
    deployment = _deployment(
        session, user_id=user_id, deployment_id=deployment_id, phase=phase, caller=current_user
    )
    vars_service.assert_writable(deployment)
    vars_service.delete_var(session, deployment=deployment, actor=current_user, key=key)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
