"""The build record.

A build transforms an uploaded project archive into a container image for one
**deployment**, and its owner is that deployment's owner: the build records no
owner of its own, so the two can never disagree. A build implies no rollout;
the client submits a successful build's ``image`` to the deployment update
endpoint itself.

There is no companion job table. Unlike ``DeploymentReconcileJobORM`` — which
exists for retry accounting, deduplication, and lease re-claiming — a build
needs none of those: failure is terminal, concurrent builds are expected, and a
stranded build is failed rather than retried. ``job_id`` doubles as the lease
token and ``started_at`` as the lease clock.
"""

from datetime import UTC, datetime
from typing import Optional
from uuid import UUID, uuid4

from pydantic import ConfigDict
from sqlmodel import Field, SQLModel
from sqlalchemy import Column, ForeignKey, Index, LargeBinary, String, Uuid

from app.models.core import _utcnow
from app.services.build_constants import (
    BUILD_STATUS_QUEUED,
    BUILD_STATUS_RUNNING,
    BUILD_STATUS_SUCCEEDED,
    BUILD_STATUSES_OPEN,
    can_transition,
    is_terminal,
)


class BuildBase(SQLModel):
    artifact_id: str


class BuildORM(BuildBase, table=True):
    __tablename__ = "build"
    __table_args__ = (
        # At most one non-terminal build per artifact, which makes creation
        # idempotent over the window in which client retries actually happen
        # without forbidding a rebuild of the same source once the previous
        # attempt is terminal.
        Index(
            "uq_open_build_per_artifact",
            "artifact_id",
            unique=True,
            postgresql_where=Column("status").in_(BUILD_STATUSES_OPEN),
        ),
    )

    id: UUID = Field(default_factory=uuid4, sa_column=Column(Uuid, primary_key=True))
    # No cascade: deployments are soft-deleted, and a build outlives its
    # deployment as the provenance of the releases that shipped it.
    deployment_id: UUID = Field(
        sa_column=Column(Uuid, ForeignKey("deployment.id"), nullable=False, index=True)
    )
    # Issued when the upload slot was minted. The object key is *derived* from
    # the deployment's owner and this value; it is never stored, so there is no
    # URL or path here whose parsing could be made load-bearing for
    # authorization.
    artifact_id: str = Field(sa_column=Column(String(), nullable=False))
    # Indexed: every build worker pass filters on it.
    status: str = Field(default=BUILD_STATUS_QUEUED, nullable=False, index=True)
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)
    # Both timestamps are the worker's to write: created_at is when the client
    # asked, started_at when a worker claimed it, finished_at when it recorded
    # a terminal status.
    started_at: Optional[datetime] = Field(default=None)
    finished_at: Optional[datetime] = Field(default=None)
    # Kubernetes Job name, written only *after* the Job exists. A null here on
    # a `running` build is therefore unambiguous — the Job was never created —
    # rather than a race the worker would have to guess about.
    job_id: Optional[str] = Field(default=None, sa_column=Column(String(), nullable=True))
    # `{owner_id}@{digest}`, with the registry host stripped off. A flat string,
    # never a structured object: it is submitted verbatim by the client as a
    # product's `image` user value, and any client-side reassembly is a place
    # for the two subsystems to drift apart on format.
    image: Optional[str] = Field(default=None, sa_column=Column(String(), nullable=True))
    # A mirror of the Job's current output, re-read in full on every worker
    # pass rather than appended to, and capped per `build_log_max_bytes`.
    #
    # Bytes, not text, because container output is a byte stream that tenant
    # code controls and this platform must not assume anything about:
    #   - Postgres `text` cannot hold a NUL byte at all, so a build that writes
    #     one to stdout would fail its log UPDATE on every worker pass, wedging
    #     itself permanently. `bytea` has no such restriction.
    #   - Decoding at ingest would otherwise force a choice between crashing
    #     the worker on invalid UTF-8 and replacing it lossily — and
    #     replacement *changes the byte length*, which would silently shift the
    #     Range offsets clients poll with.
    #   - `build_log_max_bytes` is a byte count, so truncating at the cap is a
    #     plain slice here rather than encode/slice/decode around a character
    #     that straddles the boundary.
    # The log endpoint serves these bytes as `text/plain; charset=utf-8`; UTF-8
    # is what the client should assume, not something the server enforces.
    log: bytes = Field(default=b"", sa_column=Column(LargeBinary, nullable=False))

    def transition_to(
        self,
        status: str,
        *,
        image: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> None:
        """Move this build to `status`, maintaining the timestamps and image.

        Raises ``ValueError`` for any transition the state machine does not
        permit — including every transition out of a terminal status, which is
        what makes `succeeded`, `failed`, and `canceled` final in practice and
        not merely by convention.

        `image` is accepted only alongside `succeeded`, and is required there:
        a successful build with no usable image reference is a failed build,
        and the worker is expected to record it as one.
        """
        if not can_transition(self.status, status):
            raise ValueError(f"illegal build transition: {self.status} -> {status}")

        if status == BUILD_STATUS_SUCCEEDED:
            if not image:
                raise ValueError("transition to succeeded requires an image reference")
        elif image is not None:
            raise ValueError(f"image may only be set when succeeding, not on {status}")

        stamp = now or datetime.now(UTC)
        self.status = status
        if status == BUILD_STATUS_RUNNING:
            self.started_at = stamp
        if is_terminal(status):
            self.finished_at = stamp
        if image is not None:
            self.image = image


class BuildCreate(BuildBase):
    """The entire client-supplied input to build creation: an artifact id.

    ``extra="forbid"`` is the enforcement of "neither the owner nor the
    deployment is taken from the request body" — a `user_id` or
    `deployment_id` in the payload is rejected outright rather than quietly
    dropped, so a client that believes it is choosing one finds out
    immediately.
    """

    model_config = ConfigDict(extra="forbid")


class BuildRead(BuildBase):
    id: UUID
    deployment_id: UUID
    status: str
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    # Null until the build succeeds. Neither `job_id` nor `log` is exposed:
    # the Job name is an internal detail of the worker, and the log is served
    # by its own range-capable endpoint rather than embedded in every response.
    image: Optional[str] = None
