"""Reading a deployment's application output from the log store.

The policy layer over ``loki.py``: which lines a caller may see, which release
a read is pinned to, and what one line of output looks like as an event. The
resume point, the follow loop and the stream cap are shared with the HTTP
access log and live in ``log_stream.py``.

**Every LogQL selector is built here, from a deployment row the endpoint has
already authorized, and no client-supplied string is ever interpolated into
one.** That is load-bearing rather than defensive: Loki runs with
``auth_enabled = false``, so a single tenancy holds every user's output *and*
the platform's own -- including ``caelus-api``, which logs fully merged Helm
values at INFO. A client-influenced selector would be a cross-tenant read and a
platform-secret read in the same request.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import AsyncIterator

from sqlmodel import Session, select

from app.config import CaelusSettings
from app.egress_gate import CONTAINER_NAME as EGRESS_GATE_CONTAINER
from app.models import DeploymentORM, DeploymentReleaseORM
from app.services import log_stream
from app.services.errors import NotFoundException
from app.services.log_stream import EVENT_END, LogSource, sse
from app.services.loki import LogEntry, LokiQueryClient

# The stream label Promtail derives from the `caelus.dev/release-id` pod label
# (tf/deps/loki). Named here so the one place that depends on the collector's
# contract is greppable from both ends.
RELEASE_LABEL = "release_id"

CONTAINER_LABEL = "container"
SIDECAR_CONTAINER = "ssh"
# Containers the platform adds to a tenant's pods; their output is not the app's.
PLATFORM_CONTAINERS = (SIDECAR_CONTAINER, EGRESS_GATE_CONTAINER)


@dataclass(frozen=True)
class LogTarget:
    """Everything a stream needs, resolved before the DB session is released."""

    deployment_id: str
    namespace: str
    name: str
    # Set only for a release-pinned read.
    release_id: str | None = None
    release_number: int | None = None
    # True when the pinned release has not been applied, or failed before any
    # pod started, so there is nothing that could have written a line.
    release_never_ran: bool = False


# ---------------------------------------------------------------------------
# Selector construction
# ---------------------------------------------------------------------------


def _quote(value: str) -> str:
    """Quote a label value for LogQL.

    Every value passed here comes from a database column the platform wrote --
    a namespace and Helm release name the reconciler generated, or a `uuid4`.
    Quoting anyway costs nothing and means the next caller does not have to
    know that, which is the same reasoning `garage.py` applies to its params.
    """
    return json.dumps(value)


def build_selector(target: LogTarget) -> str:
    """The LogQL stream selector for one deployment, or one of its releases.

    `{namespace, instance}` already selects exactly one deployment's output,
    live and historical, including pods deleted minutes ago -- `namespace` is
    the per-user namespace and `instance` is the Helm release name, which is
    `deployment.name`. Adding `release_id` narrows it to a single rollout.
    """
    matchers = [
        f"namespace={_quote(target.namespace)}",
        f"instance={_quote(target.name)}",
        *(f"{CONTAINER_LABEL}!={_quote(c)}" for c in PLATFORM_CONTAINERS),
    ]
    if target.release_id is not None:
        matchers.append(f"{RELEASE_LABEL}={_quote(target.release_id)}")
    return "{" + ", ".join(matchers) + "}"


# ---------------------------------------------------------------------------
# Resolving what to read, under the session
# ---------------------------------------------------------------------------


def resolve_target(
    session: Session,
    *,
    deployment_id,
    user_id: int | None,
    release_number: int | None = None,
) -> LogTarget:
    """Authorize the deployment and resolve everything the stream will need.

    Called while the request still holds a database session; the stream itself
    holds none. Reading a deployment's log is authorized exactly like every
    other user-scoped deployment route, and a deployment belonging to another
    user answers 404 -- indistinguishable from one that does not exist, so the
    endpoint cannot be used to discover other users' deployments.
    """
    deployment = session.get(DeploymentORM, deployment_id)
    if deployment is None or (user_id is not None and deployment.user_id != user_id):
        raise NotFoundException("Deployment not found")

    if release_number is None:
        return LogTarget(
            deployment_id=str(deployment.id),
            namespace=deployment.namespace,
            name=deployment.name,
        )

    release = session.exec(
        select(DeploymentReleaseORM)
        .where(DeploymentReleaseORM.deployment_id == deployment.id)
        .where(DeploymentReleaseORM.number == release_number)
    ).first()
    if release is None:
        # Scoped to the addressed deployment, so naming another deployment's
        # release number returns nothing from it.
        raise NotFoundException(f"Release {release_number} not found for this deployment")

    return LogTarget(
        deployment_id=str(deployment.id),
        namespace=deployment.namespace,
        name=deployment.name,
        release_id=str(release.id),
        release_number=release.number,
        # Never started means no pod ever carried the label, which is a
        # different answer from "ran and printed nothing".
        release_never_ran=release.started_at is None,
    )


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------

EVENT_LOG = "log"
END_RELEASE_NEVER_RAN = "release_never_ran"


def render(entry: LogEntry) -> dict:
    """One line of application output.

    `ts` is a **string**, and must stay one. A nanosecond timestamp is ~1.76e18
    against a `Number.MAX_SAFE_INTEGER` of ~9.01e15, so a JSON number would be
    silently rounded by any JavaScript consumer -- corrupting both the
    displayed time and the resume point with no error raised. `ui/` makes that
    concrete.
    """
    return {
        "ts": entry.timestamp_ns,
        "line": entry.line,
        # Null for a pod without the label -- a datastore, or a release
        # from before its chart rendered one -- which is not an error.
        "release": entry.labels.get(RELEASE_LABEL),
    }


def log_source(target: LogTarget) -> LogSource:
    return LogSource(
        selector=build_selector(target),
        event=EVENT_LOG,
        render=render,
        description=f"deployment_id={target.deployment_id}",
    )


async def fetch_initial(
    client: LokiQueryClient,
    target: LogTarget,
    *,
    tail: int,
    resume_ns: int | None,
    settings: CaelusSettings,
    lookback_seconds: int | None = None,
) -> list[LogEntry]:
    return await log_stream.fetch_initial(
        client,
        build_selector(target),
        tail=tail,
        resume_ns=resume_ns,
        settings=settings,
        lookback_seconds=lookback_seconds,
    )


async def stream_log(
    client: LokiQueryClient,
    target: LogTarget,
    *,
    initial: list[LogEntry],
    follow: bool,
    settings: CaelusSettings | None = None,
) -> AsyncIterator[str]:
    if target.release_never_ran:
        # Not a silent empty stream: that would be indistinguishable from an
        # application that printed nothing, which is a different claim.
        yield sse(
            EVENT_END,
            {
                "reason": END_RELEASE_NEVER_RAN,
                "release": target.release_number,
                "message": (
                    f"Release {target.release_number} produced no output because it "
                    f"never ran."
                ),
            },
        )
        return
    async for chunk in log_stream.stream(
        client, log_source(target), initial=initial, follow=follow, settings=settings
    ):
        yield chunk
