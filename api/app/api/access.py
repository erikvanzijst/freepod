from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Response, status
from sqlmodel import Session

from app.db import get_session
from app.deps import require_self
from app.models import AccessEntryCreate, AccessEntryRead, AccessListRead, UserORM
from app.services import app_access
from app.services import deployments as deployment_service
from app.services.errors import InvalidInputException

router = APIRouter(
    prefix="/users/{user_id}/deployments/{deployment_id}/access",
    tags=["access"],
)


def _owner_only(current_user: UserORM, user_id: int) -> None:
    """Changing who may sign in is the owner's alone, administrators included."""
    if current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the deployment's owner can change who may sign in to it.",
        )


@router.get(
    "",
    response_model=AccessListRead,
    summary="Read who may sign in to a deployment",
    response_description="The deployment's authentication settings, its owner, and its access list.",
    responses={
        403: {"description": "Caller may only read their own deployments."},
        404: {"description": "No such deployment exists for this user."},
    },
)
def read_access(
    user_id: int = Path(..., description="ID of the user that owns the deployment."),
    deployment_id: UUID = Path(..., description="UUID of the deployment."),
    current_user: UserORM = Depends(require_self),
    session: Session = Depends(get_session),
) -> AccessListRead:
    """Return who may sign in to a deployment with Sign in with Freepod.

    ## Authorization
    You may read your own deployments' access; administrators may read any
    account's. Other requests receive `403 Forbidden`.

    ## Behavior
    `enabled`, `protocol` and `access` are the serving release's settings,
    defaults applied. The owner is always admitted and is never an entry. The
    whole list is returned, at most `limit` entries. An entry with `bound_at`
    has been signed in with, and from then on admits only that account.
    """
    deployment = deployment_service.get_deployment_orm(
        session, deployment_id=deployment_id, user_id=None if current_user.is_admin else user_id
    )
    return app_access.read_access(session, deployment)


@router.post(
    "",
    response_model=AccessEntryRead,
    status_code=status.HTTP_201_CREATED,
    summary="Let someone sign in to a deployment",
    response_description="The new entry, not yet signed in with.",
    responses={
        403: {"description": "Only the deployment's owner may change its access list."},
        404: {"description": "No such deployment exists for this user."},
        409: {"description": "Already admitted (`access_duplicate`), the list is full (`access_list_full`), or the serving release is not `listed` (`access_not_listed`)."},
        422: {"description": "Not a valid email address (`access_invalid_email`)."},
        429: {"description": "The owner's daily invitation limit is reached (`access_invitation_limit`)."},
    },
)
def add_access(
    payload: AccessEntryCreate,
    background: BackgroundTasks,
    user_id: int = Path(..., description="ID of the user that owns the deployment."),
    deployment_id: UUID = Path(..., description="UUID of the deployment."),
    current_user: UserORM = Depends(require_self),
    session: Session = Depends(get_session),
) -> AccessEntryRead:
    """Add an email address to a `listed` deployment's access list.

    ## Authorization
    **The owner only.** Administrators may read a deployment's list but not
    change it.

    ## Behavior
    The address is stored in lower case. Whoever first signs in with a Freepod
    account using it is admitted, and from then on only that account. The
    address receives one invitation email naming the owner and the app's
    address; failing to send it does not undo the addition. Each owner may
    send a limited number of invitations a day, across all their deployments,
    and removing entries does not return them.
    """
    _owner_only(current_user, user_id)
    email = app_access.normalize_email(payload.email)
    if email is None:
        raise InvalidInputException(f"{payload.email!r} is not a valid email address", code="access_invalid_email")
    deployment = deployment_service.get_deployment_orm(session, deployment_id=deployment_id, user_id=user_id)
    entry, invitation = app_access.add_entry(session, deployment, email)
    background.add_task(app_access.send_invitation, invitation)
    return entry


@router.delete(
    "/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Stop someone signing in to a deployment",
    responses={
        403: {"description": "Only the deployment's owner may change its access list."},
        404: {"description": "No such deployment for this user, or no such entry on its list."},
        502: {"description": "The app did not accept signing the person out (`access_logout_failed`); the entry stays."},
    },
)
def remove_access(
    user_id: int = Path(..., description="ID of the user that owns the deployment."),
    deployment_id: UUID = Path(..., description="UUID of the deployment."),
    entry_id: UUID = Path(..., description="ID of the entry to remove."),
    current_user: UserORM = Depends(require_self),
    session: Session = Depends(get_session),
) -> Response:
    """Remove an entry from a deployment's access list.

    ## Authorization
    **The owner only**, as for adding.

    ## Behavior
    A header app refuses the person within 30 seconds. For an app that signs
    in over OpenID Connect and accepts back-channel logout, an entry that has
    been signed in with is removed only once the app has accepted a logout
    token for that account; otherwise the answer is `502` and the entry stays.
    What the person stored in the app is not touched.
    """
    _owner_only(current_user, user_id)
    deployment = deployment_service.get_deployment_orm(session, deployment_id=deployment_id, user_id=user_id)
    app_access.remove_entry(session, deployment, entry_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
