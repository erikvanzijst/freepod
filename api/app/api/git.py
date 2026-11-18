from __future__ import annotations

from typing import Optional
from uuid import UUID
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from app.config import get_settings
from app.db import get_session
from app.deps import get_current_user, require_self
from app.models import (
    DeploymentSourceRead,
    DeploymentSourceWrite,
    GitConnectionRead,
    GitCredentialRead,
    GitCredentialRequest,
    GitHubRepositoryCreate,
    GitHubRepositoryListing,
    GitHubRepositoryRead,
    GitHubConnectStart,
    GitHubInstallationRead,
    UserORM,
)
from app.services import deployment_sources, github
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


@router.post(
    "/users/{user_id}/git/github/repositories",
    response_model=GitHubRepositoryRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a GitHub repository",
    responses={
        403: {
            "description": "Only the account's owner may create repositories, and only where "
            "GitHub lets them (`github_repo_create_forbidden`, `github_repo_owner_invalid`)."
        },
        404: {"description": "The Freepod app is not installed on that account (`github_app_not_installed`)."},
        409: {
            "description": "Not connected (`git_not_connected`), the name is taken "
            "(`github_repo_exists`), or the repository was created but the app cannot reach it "
            "(`github_repo_not_reachable`)."
        },
        422: {"description": "The name is not a valid repository name (`github_repo_name_invalid`)."},
    },
)
def create_github_repository(
    payload: GitHubRepositoryCreate,
    user_id: int = Path(..., description="ID of the account."),
    current_user: UserORM = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> GitHubRepositoryRead:
    """Create an empty repository on the connected GitHub user's account, or on an
    organization when `owner` names one, private unless `private` is false.

    The Freepod app must be installed on that account. When the installation is
    limited to selected repositories, the new repository is added to it.
    """
    _require_owner(user_id, current_user)
    return GitHubRepositoryRead(
        **github.create_repository(
            session,
            user_id,
            name=payload.name,
            owner=payload.owner,
            private=payload.private,
            description=payload.description,
        )
    )


@router.post(
    "/users/{user_id}/git/github/credentials",
    response_model=GitCredentialRead,
    summary="Get a short-lived git credential for one repository",
    responses={
        403: {
            "description": "Only the account's owner may get credentials, and only with the "
            "access their GitHub account has (`github_repo_forbidden`)."
        },
        404: {
            "description": "The repository does not exist or the app cannot reach it "
            "(`github_repo_not_found`, `github_app_not_installed`)."
        },
        409: {"description": "The account is not connected (`git_not_connected`)."},
    },
)
def mint_git_credential(
    payload: GitCredentialRequest,
    response: Response,
    user_id: int = Path(..., description="ID of the account."),
    current_user: UserORM = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> GitCredentialRead:
    """A username and password for git over HTTPS that work for one hour, on one
    repository's contents only, with `read` or `write` access.

    The connected GitHub user must have that access to the repository themselves.
    This is what `freepod git credential` hands to git; it never stores it.
    """
    _require_owner(user_id, current_user)
    response.headers["Cache-Control"] = "no-store"
    return GitCredentialRead(
        **github.mint_credential(
            session, user_id, repository=payload.repository, access=payload.access
        )
    )


@router.get(
    "/users/{user_id}/git/github/repositories",
    response_model=list[GitHubRepositoryListing],
    summary="List the GitHub repositories the Freepod app can reach",
    responses={
        403: {"description": "Caller may only list their own repositories."},
        409: {"description": "The account is not connected (`git_not_connected`)."},
    },
)
def list_github_repositories(
    user_id: int = Path(..., description="ID of the account."),
    current_user: UserORM = Depends(require_self),
    session: Session = Depends(get_session),
) -> list[GitHubRepositoryListing]:
    """Every repository of every installation the connected user can see, most
    recently pushed first, up to 1000."""
    return [
        GitHubRepositoryListing(**item) for item in github.list_repositories(session, user_id)
    ]


SOURCE_PATH = "/users/{user_id}/deployments/{deployment_id}/source"


@router.get(
    SOURCE_PATH,
    response_model=DeploymentSourceRead,
    summary="Show the repository a deployment is built from",
    responses={404: {"description": "No such deployment, or it is not linked (`source_not_linked`)."}},
)
def get_deployment_source(
    user_id: int = Path(..., description="ID of the deployment's owner."),
    deployment_id: UUID = Path(..., description="ID of the deployment."),
    current_user: UserORM = Depends(require_self),
    session: Session = Depends(get_session),
) -> DeploymentSourceRead:
    return deployment_sources.get_source(session, user_id=user_id, deployment_id=deployment_id)


@router.put(
    SOURCE_PATH,
    response_model=DeploymentSourceRead,
    summary="Link a deployment to the repository it is built from",
    responses={
        403: {"description": "Only the deployment's owner may link it."},
        404: {
            "description": "No such deployment, or the repository does not exist or the app "
            "cannot reach it (`github_repo_not_found`, `github_app_not_installed`)."
        },
        409: {"description": "The account is not connected to GitHub (`git_not_connected`)."},
        422: {
            "description": "The repository, branch or path is not valid "
            "(`github_repo_name_invalid`, `source_branch_invalid`, `source_root_invalid`)."
        },
    },
)
def put_deployment_source(
    payload: DeploymentSourceWrite,
    user_id: int = Path(..., description="ID of the deployment's owner."),
    deployment_id: UUID = Path(..., description="ID of the deployment."),
    current_user: UserORM = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> DeploymentSourceRead:
    """Record which GitHub repository, branch and directory in it the deployment is
    built from, replacing any earlier link.

    The repository is identified by GitHub's own id, so a rename or a transfer
    keeps the link. `branch` defaults to the repository's default branch, and
    `root_dir`, the directory holding the project, to the repository's root.
    Nothing is built or released.
    """
    _require_owner(user_id, current_user)
    return deployment_sources.link(
        session,
        user_id=user_id,
        deployment_id=deployment_id,
        repository=payload.repository,
        branch=payload.branch,
        root_dir=payload.root_dir,
    )


@router.delete(
    SOURCE_PATH,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unlink a deployment from its repository",
    responses={
        403: {"description": "Only the deployment's owner may unlink it."},
        404: {"description": "No such deployment, or it is not linked (`source_not_linked`)."},
    },
)
def delete_deployment_source(
    user_id: int = Path(..., description="ID of the deployment's owner."),
    deployment_id: UUID = Path(..., description="ID of the deployment."),
    current_user: UserORM = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> Response:
    _require_owner(user_id, current_user)
    deployment_sources.unlink(session, user_id=user_id, deployment_id=deployment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
