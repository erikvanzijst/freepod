"""Build lifecycle: creation, retrieval, listing, and log slicing.

A build belongs to a deployment, and every call here is scoped by the owner
and deployment named in the request path: the deployment must belong to that
owner, and the build to that deployment. Anything else raises
``NotFoundException`` rather than a permission error, so another owner's build,
or one addressed under the wrong deployment, is indistinguishable from one that
never existed. Whether the caller may act as that owner is the API's
self-or-administrator guard, not this module's.

A deleted deployment's builds stay readable: they are the provenance of the
releases that shipped them. Only creation refuses such a deployment.

Nothing in this module writes build *state* beyond creating the row. The
timestamps, `job_id`, `image`, and `log` all belong to the build worker — it is
the single writer for everything downstream of `queued`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models import BuildCreate, BuildORM, BuildRead, DeploymentORM
from app.services.artifacts import artifact_exists, validate_artifact_id
from app.services.build_constants import BUILD_STATUSES_OPEN
from app.services.errors import IntegrityException, NotFoundException, ValidationException
from app.services.reconcile_constants import (
    DEPLOYMENT_STATUS_DELETED,
    DEPLOYMENT_STATUS_DELETING,
)

logger = logging.getLogger(__name__)


@dataclass
class BuildCreateResult:
    """The build, and whether this request is what brought it into existence.

    `created` is false when an in-flight build for the same artifact was
    returned instead, which lets the endpoint answer 201 for a real creation
    and 200 for an idempotent retry.
    """

    build: BuildRead
    created: bool


@dataclass
class BuildLogSlice:
    """A window onto a build's output.

    `data` is raw bytes, straight out of the column. The log is stored as
    `bytea` precisely so that neither this nor the worker has to decode a
    tenant-controlled byte stream, and so that HTTP's byte offsets and the
    column's own length are the same number.

    `start` is the byte offset `data` begins at, after clamping — a client that
    polls from the current end of a growing log gets an empty `data` and a
    `start` at the end, not an error.
    """

    data: bytes
    start: int
    status: str
    partial: bool


def _get_deployment(session: Session, *, user_id: int, deployment_id: UUID) -> DeploymentORM:
    """The owner's deployment, deleted or not; anyone else's is not found."""
    deployment = session.get(DeploymentORM, deployment_id)
    if deployment is None or deployment.user_id != user_id:
        raise NotFoundException("Deployment not found")
    return deployment


def _get_build_orm(
    session: Session, *, user_id: int, deployment_id: UUID, build_id: UUID
) -> BuildORM:
    _get_deployment(session, user_id=user_id, deployment_id=deployment_id)
    build = session.get(BuildORM, build_id)
    if build is None or build.deployment_id != deployment_id:
        # Same answer for "does not exist", "is not yours" and "belongs to
        # another deployment": a caller must not be able to probe for builds.
        raise NotFoundException("Build not found")
    return build


def build_owner_id(session: Session, build: BuildORM) -> int:
    """The build's owner, which is its deployment's: a build records none."""
    owner_id = session.exec(
        select(DeploymentORM.user_id).where(DeploymentORM.id == build.deployment_id)
    ).one()
    return owner_id


def _open_build_for(
    session: Session, *, deployment: DeploymentORM, artifact_id: str
) -> BuildORM | None:
    """The in-flight build of `artifact_id` for this deployment, if any.

    One the same owner started for a *different* deployment is refused as a
    conflict: returning it would answer a request about this deployment with a
    build of another. One belonging to another owner is ignored, so its
    existence does not leak; the artifact check that follows cannot find that
    owner's artifact under this one's prefix anyway.
    """
    row = session.exec(
        select(BuildORM, DeploymentORM.user_id)
        .join(DeploymentORM, DeploymentORM.id == BuildORM.deployment_id)
        .where(BuildORM.artifact_id == artifact_id)
        .where(BuildORM.status.in_(BUILD_STATUSES_OPEN))  # type: ignore[attr-defined]
    ).first()
    if row is None:
        return None
    build, owner_id = row
    if owner_id != deployment.user_id:
        return None
    if build.deployment_id != deployment.id:
        raise IntegrityException(
            "This artifact is already being built for another deployment"
        )
    return build


def create_build(
    session: Session, *, user_id: int, deployment_id: UUID, payload: BuildCreate
) -> BuildCreateResult:
    """Queue a build of a previously uploaded artifact for a deployment.

    The deployment comes from the path and the owner from the deployment:
    `payload` carries only an artifact id and forbids extra fields, so there is
    neither in the request to honor. A deployment being deleted, or already
    deleted, takes no builds, since nothing could ever be released into it.

    Creation is idempotent over the window in which client retries actually
    happen. A retry arriving while the original build is still `queued` or
    `running` gets that build back; once every build for the artifact is
    terminal, a fresh one is created, because build failures are often
    transient and re-uploading an identical archive to retry would waste the
    upload for nothing.
    """
    artifact_id = validate_artifact_id(payload.artifact_id)
    deployment = _get_deployment(session, user_id=user_id, deployment_id=deployment_id)
    if deployment.status in (DEPLOYMENT_STATUS_DELETING, DEPLOYMENT_STATUS_DELETED):
        raise ValidationException(
            f"Deployment {deployment_id} is {deployment.status} and takes no builds"
        )

    existing = _open_build_for(session, deployment=deployment, artifact_id=artifact_id)
    if existing is not None:
        logger.info(
            "Build create is a retry; returning in-flight build id=%s deployment_id=%s",
            existing.id,
            deployment_id,
        )
        return BuildCreateResult(build=BuildRead.model_validate(existing), created=False)

    # Deliberately after the retry check: a build already in flight proves the
    # artifact was there when it started, and re-checking would both cost a
    # needless round trip and fail a legitimate retry whose artifact has since
    # been expired by the bucket's lifecycle rule.
    if not artifact_exists(deployment.user_id, artifact_id):
        raise ValidationException(
            f"Artifact {artifact_id} was not found; upload it before creating a build"
        )

    build = BuildORM(deployment_id=deployment_id, artifact_id=artifact_id)
    session.add(build)
    try:
        session.commit()
    except IntegrityError as exc:
        # Two creations raced. The partial unique index is the arbiter; the
        # loser adopts the winner's build rather than reporting a conflict.
        session.rollback()
        winner = _open_build_for(session, deployment=deployment, artifact_id=artifact_id)
        if winner is None:
            logger.warning(
                "Build create conflicted for artifact_id=%s deployment_id=%s",
                artifact_id,
                deployment_id,
            )
            raise IntegrityException("A build for this artifact is already in flight") from exc
        return BuildCreateResult(build=BuildRead.model_validate(winner), created=False)

    session.refresh(build)
    logger.info(
        "Queued build id=%s deployment_id=%s artifact_id=%s", build.id, deployment_id, artifact_id
    )
    return BuildCreateResult(build=BuildRead.model_validate(build), created=True)


def get_build(
    session: Session, *, user_id: int, deployment_id: UUID, build_id: UUID
) -> BuildRead:
    return BuildRead.model_validate(
        _get_build_orm(session, user_id=user_id, deployment_id=deployment_id, build_id=build_id)
    )


def list_builds(session: Session, *, user_id: int, deployment_id: UUID) -> list[BuildRead]:
    """A deployment's builds, most recent first.

    Enumeration is what makes a previously produced image reachable again
    after a client has forgotten its build id — which is exactly what a
    redeploy or a rollback needs.
    """
    _get_deployment(session, user_id=user_id, deployment_id=deployment_id)
    stmt = (
        select(BuildORM)
        .where(BuildORM.deployment_id == deployment_id)
        .order_by(BuildORM.created_at.desc(), BuildORM.id.desc())  # type: ignore[attr-defined]
    )
    return [BuildRead.model_validate(b) for b in session.exec(stmt).all()]


def get_build_log(
    session: Session,
    *,
    user_id: int,
    deployment_id: UUID,
    build_id: UUID,
    start: int | None = None,
    end: int | None = None,
) -> BuildLogSlice:
    """A build's output, optionally from `start` to `end` (inclusive, bytes).

    `start` past the current end of the log yields an empty slice rather than
    an error: the log grows while the build runs, so a client polling from the
    offset it last read to is in the *steady* state, not an exceptional one,
    and should not have to special-case it.
    """
    build = _get_build_orm(
        session, user_id=user_id, deployment_id=deployment_id, build_id=build_id
    )
    # `bytes(...)` normalizes whatever the driver hands back for a binary
    # column (psycopg gives bytes, some drivers a memoryview) so slicing and
    # `len` are uniform.
    data = bytes(build.log or b"")

    if start is None:
        return BuildLogSlice(data=data, start=0, status=build.status, partial=False)

    # Clamp rather than reject, so `start` is always a truthful offset for the
    # bytes actually returned.
    offset = min(max(start, 0), len(data))
    window = data[offset:] if end is None else data[offset : end + 1]
    return BuildLogSlice(data=window, start=offset, status=build.status, partial=True)
