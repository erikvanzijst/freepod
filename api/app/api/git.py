from __future__ import annotations

from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from app.config import get_settings
from app.db import get_session
from app.deps import get_current_user, require_self
from app.models import (
    GitConnectionRead,
    GitHubConnectStart,
    GitHubInstallationRead,
    UserORM,
)
from app.services import github
from app.services.errors import CaelusException

router = APIRouter(tags=["git"])

SETTINGS_PATH = "/settings/git"


def _require_owner(user_id: int, current_user: UserORM) -> None:
    if current_user.id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


@router.get(
    "/users/{user_id}/git",
    response_model=list[GitConnectionRead],
    summary="List an account's git hosting connections",
    responses={403: {"description": "Caller may only read their own connections."}},
)
def list_git_connections(
    user_id: int = Path(..., description="ID of the account."),
    current_user: UserORM = Depends(require_self),
    session: Session = Depends(get_session),
) -> list[GitConnectionRead]:
    """The git hosts this account is connected to; an empty array when none.

    `expires_at` is when the connection lapses unless it is used before then:
    every use renews it.
    """
    return github.list_connections(session, user_id)


@router.post(
    "/users/{user_id}/git/github/connect",
    response_model=GitHubConnectStart,
    summary="Start connecting an account to GitHub",
    responses={
        403: {"description": "Only the account's owner may connect it."},
        503: {"description": "This environment has no GitHub App (`github_unavailable`)."},
    },
)
def start_github_connect(
    user_id: int = Path(..., description="ID of the account."),
    current_user: UserORM = Depends(get_current_user),
) -> GitHubConnectStart:
    """Links to send the owner's browser to, valid for 30 minutes.

    `authorize_url` lets the Freepod GitHub App act for the user.
    `install_url` installs the app on a GitHub account or organization and
    chooses its repositories; it authorizes the user on the way. Both return to
    the callback, signed in to Freepod as the same account, and from there to
    the Git settings page. A client that cannot follow the redirect polls
    `GET /users/{user_id}/git` until the connection appears.
    """
    _require_owner(user_id, current_user)
    return GitHubConnectStart(**github.connect_urls(user_id))


@router.get(
    "/git/github/callback",
    include_in_schema=False,
)
def github_callback(
    state: Optional[str] = Query(None),
    code: Optional[str] = Query(None),
    setup_action: Optional[str] = Query(None),
    current_user: UserORM = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    """Where GitHub returns the browser; always answers with a redirect to Settings."""
    outcome: dict[str, str]
    if code is None:
        outcome = {"github": "requested" if setup_action == "request" else "canceled"}
    elif state is None:
        outcome = {"github_error": "github_state_invalid"}
    else:
        try:
            github.complete_authorization(session, current_user.id, code=code, state=state)
            outcome = {"github": "connected"}
        except CaelusException as exc:
            outcome = {"github_error": getattr(exc, "code", None) or "github_error"}
    base = get_settings().base_url.rstrip("/")
    return RedirectResponse(f"{base}{SETTINGS_PATH}?{urlencode(outcome)}", status_code=303)


@router.delete(
    "/users/{user_id}/git/github",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disconnect an account from GitHub",
    responses={
        403: {"description": "Caller may only disconnect their own account."},
        409: {"description": "The account is not connected (`git_not_connected`)."},
    },
)
def disconnect_github(
    user_id: int = Path(..., description="ID of the account."),
    current_user: UserORM = Depends(require_self),
    session: Session = Depends(get_session),
) -> Response:
    """Revoke the Freepod GitHub App's authorization and forget the connection.

    The app stays installed on the GitHub accounts it was installed on; they
    uninstall it in their GitHub settings.
    """
    github.disconnect(session, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/users/{user_id}/git/github/installations",
    response_model=list[GitHubInstallationRead],
    summary="List the GitHub accounts the Freepod app is installed on",
    responses={
        403: {"description": "Caller may only read their own installations."},
        409: {"description": "The account is not connected (`git_not_connected`)."},
    },
)
def list_github_installations(
    user_id: int = Path(..., description="ID of the account."),
    current_user: UserORM = Depends(require_self),
    session: Session = Depends(get_session),
) -> list[GitHubInstallationRead]:
    """The installations the connected GitHub user can see: their own account's
    and their organizations'. A repository is reachable through Freepod only if
    one of these covers it."""
    return [
        GitHubInstallationRead(**item) for item in github.list_installations(session, user_id)
    ]
