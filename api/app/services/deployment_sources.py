"""The repository a deployment is built from: linked, read and unlinked by its owner."""

from __future__ import annotations

import posixpath
import re
from typing import Any, Optional
from uuid import UUID

import httpx
from sqlmodel import Session

from app.models.core import _utcnow
from app.models.git import DeploymentSourceORM, DeploymentSourceRead, GitProvider
from app.services import github
from app.services.deployments import get_deployment_orm
from app.services.errors import CodedNotFoundException, InvalidInputException

BRANCH = re.compile(r"^(?!-)(?!/)(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,255}(?<!/)(?<!\.lock)$")


def _not_linked() -> CodedNotFoundException:
    return CodedNotFoundException(
        "This deployment is not linked to a repository.", code="source_not_linked"
    )


def _read(row: DeploymentSourceORM) -> DeploymentSourceRead:
    return DeploymentSourceRead(
        provider=row.provider,
        host=row.host,
        repository_id=row.repository_id,
        full_name=row.full_name,
        html_url=f"https://{row.host}/{row.full_name}",
        branch=row.branch,
        root_dir=row.root_dir,
        linked_at=row.created_at,
    )


def normalize_root_dir(value: str) -> str:
    """A path inside the repository, as `dir/sub` without slashes at its ends; "" is the root."""
    if "\\" in value or "\x00" in value:
        raise InvalidInputException("The path uses / between directories.", code="source_root_invalid")
    if value.startswith("/"):
        raise InvalidInputException(
            "The path is relative to the repository's root.", code="source_root_invalid"
        )
    normalized = posixpath.normpath(value) if value.strip("/") else "."
    if normalized == ".":
        return ""
    if normalized == ".." or normalized.startswith("../") or len(normalized) > 1024:
        raise InvalidInputException("The path must stay inside the repository.", code="source_root_invalid")
    return normalized


def get_source(session: Session, *, user_id: Any, deployment_id: UUID) -> DeploymentSourceRead:
    get_deployment_orm(session, deployment_id=deployment_id, user_id=user_id)
    row = session.get(DeploymentSourceORM, deployment_id)
    if row is None:
        raise _not_linked()
    return _read(row)


def link(
    session: Session,
    *,
    user_id: Any,
    deployment_id: UUID,
    repository: str,
    branch: Optional[str] = None,
    root_dir: str = "",
    client: Optional[httpx.Client] = None,
) -> DeploymentSourceRead:
    """Link the deployment to a GitHub repository its owner can see and the app can reach."""
    get_deployment_orm(session, deployment_id=deployment_id, user_id=user_id)
    root = normalize_root_dir(root_dir)
    if branch is not None and not BRANCH.match(branch):
        raise InvalidInputException(f"{branch!r} is not a branch name.", code="source_branch_invalid")
    repo = github.resolve_repository(session, user_id, repository, client=client)
    chosen = branch or repo["default_branch"] or "main"

    row = session.get(DeploymentSourceORM, deployment_id)
    if row is None:
        row = DeploymentSourceORM(
            deployment_id=deployment_id,
            provider=GitProvider.GITHUB,
            host=github.HOST,
            repository_id="",
            full_name="",
            branch="",
        )
    row.provider = GitProvider.GITHUB
    row.host = github.HOST
    row.repository_id = str(repo["id"])
    row.full_name = repo["full_name"]
    row.branch = chosen
    row.root_dir = root
    row.installation_id = str(repo["installation_id"])
    row.updated_at = _utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return _read(row)


def unlink(session: Session, *, user_id: Any, deployment_id: UUID) -> None:
    get_deployment_orm(session, deployment_id=deployment_id, user_id=user_id)
    row = session.get(DeploymentSourceORM, deployment_id)
    if row is None:
        raise _not_linked()
    session.delete(row)
    session.commit()
