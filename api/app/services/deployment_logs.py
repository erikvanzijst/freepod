"""Reading a deployment's application output from the log store.

The policy layer over ``loki.py``: which lines a caller may see, how a resume
point is validated, what a Server-Sent Events stream looks like, and how an
unavailable store is distinguished from an application that printed nothing.

**Every LogQL selector is built here, from a deployment row the endpoint has
already authorized, and no client-supplied string is ever interpolated into
one.** That is load-bearing rather than defensive: Loki runs with
``auth_enabled = false``, so a single tenancy holds every user's output *and*
the platform's own -- including ``caelus-api``, which logs fully merged Helm
values at INFO. A client-influenced selector would be a cross-tenant read and a
platform-secret read in the same request.

The one client-supplied value that reaches a query is the resume timestamp, and
it becomes an ``int`` before it goes anywhere near one. That the client
legitimately holds the value does not make it trusted.
"""

from __future__ import annotations

from dataclasses import dataclass
import asyncio
import json
import logging
import time
from typing import AsyncIterator

from sqlmodel import Session, select

from app.config import CaelusSettings, get_settings
from app.models import DeploymentORM, DeploymentReleaseORM
from app.services.errors import NotFoundException, ValidationException
from app.services.loki import (
    DIRECTION_BACKWARD,
    DIRECTION_FORWARD,
    LogEntry,
    LokiException,
    LokiQueryClient,
)

logger = logging.getLogger(__name__)

# The stream label Promtail derives from the `caelus.dev/release-id` pod label
# (tf/deps/loki). Named here so the one place that depends on the collector's
# contract is greppable from both ends.
RELEASE_LABEL = "release_id"

CONTAINER_LABEL = "container"
SIDECAR_CONTAINER = "ssh"

NS_PER_SECOND = 1_000_000_000
# A nanosecond timestamp is a uint64. The lower bound rejects a value in
# seconds or milliseconds -- a plausible client mistake that would otherwise
# silently ask for everything since 1970 -- by requiring it to be at least
# 2001-09-09, the point where second-resolution epochs stopped being 9 digits.
MIN_TIMESTAMP_NS = 1_000_000_000 * NS_PER_SECOND
MAX_TIMESTAMP_NS = 2**64 - 1


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
        f"{CONTAINER_LABEL}!={_quote(SIDECAR_CONTAINER)}",
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
# The resume point
# ---------------------------------------------------------------------------


def parse_resume_timestamp(value: str | None) -> int | None:
    """Validate a client-supplied resume point before it can become `start`.

    The single exception to "queries carry nothing from the client", and only
    because the value becomes a number first. Parsed as a `uint64` in a sane
    range and rejected otherwise; never forwarded to the store as an
    unvalidated string.

    `int(...)`, never `float(...)`: a nanosecond timestamp is ~1.76e18 against
    a double's exact-integer ceiling of ~9.01e15, so any float round trip
    corrupts it silently.
    """
    if value is None or value == "":
        return None
    text = value.strip()
    if not text.isdigit():
        raise ValidationException(
            "Resume point must be a nanosecond timestamp expressed in decimal digits"
        )
    parsed = int(text)
    if not (MIN_TIMESTAMP_NS <= parsed <= MAX_TIMESTAMP_NS):
        raise ValidationException("Resume point is not a plausible nanosecond timestamp")
    return parsed


# ---------------------------------------------------------------------------
# Server-Sent Events
# ---------------------------------------------------------------------------
#
# Chosen over a WebSocket because the traffic is unidirectional -- a return
# channel nothing would use, at the cost of a client dependency (`httpx` has no
# WebSocket support) and of reimplementing `ApiClient`'s refresh contract for
# one endpoint. Chosen over an unframed body because a long-lived stream has to
# survive silence, and every improvisation on plain text is bad: a blank line
# pollutes output that must survive `freepod log > app.log`, and a zero-length
# chunk terminates the response.
#
# SSE gives three things plain text cannot express in band: a heartbeat that is
# a first-class idiom (a line beginning with `:` is a comment clients must
# ignore), `event: error` before a mid-stream close, and `id:` for resumption.
# It costs nothing that made chunked HTTP attractive -- still plain HTTP, still
# `iter_lines()`, still no new client dependency, still curl-able.

EVENT_LOG = "log"
EVENT_ERROR = "error"
EVENT_END = "end"

# Clean-ending reasons, so a client can tell "that is all there is" from
# "the platform gave up" without parsing prose. `lifetime` in particular is a
# *resumable* ending: the client reconnects from its cursor and loses nothing.
END_COMPLETE = "complete"
END_LIFETIME = "lifetime"
END_RELEASE_NEVER_RAN = "release_never_ran"


def _sse(event: str, data: dict, *, event_id: str | None = None) -> str:
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, separators=(',', ':'))}")
    return "\n".join(lines) + "\n\n"


def _keepalive() -> str:
    """A comment, not an event.

    It belongs to a lower layer than the log stream: it describes the
    connection, not the log. Carrying no `id:` is the point -- advancing a
    cursor from a keepalive would move the resume point past instants at which
    no line was delivered, permanently skipping any line that arrives late
    bearing an earlier timestamp, which an unadvanced cursor still collects on
    the next resume.
    """
    return ": keepalive\n\n"


def _log_event(entry: LogEntry) -> str:
    """One log line.

    `ts` is a **string**, and must stay one. A nanosecond timestamp is ~1.76e18
    against a `Number.MAX_SAFE_INTEGER` of ~9.01e15, so a JSON number would be
    silently rounded by any JavaScript consumer -- corrupting both the
    displayed time and the resume point with no error raised. `ui/` makes that
    concrete.

    The same value is mirrored into `id:` so a stock `EventSource` gets
    `Last-Event-ID` for free; the contract names the `ts` field.
    """
    return _sse(
        EVENT_LOG,
        {
            "ts": entry.timestamp_ns,
            "line": entry.line,
            # Null for a pod without the label -- a datastore, or a release
            # from before its chart rendered one -- which is not an error.
            "release": entry.labels.get(RELEASE_LABEL),
        },
        event_id=entry.timestamp_ns,
    )


class _Cursor:
    """The resume point, and what has already been delivered at it.

    Resumption is inclusive -- `start` is the last timestamp seen, not one
    nanosecond after it -- because every undelivered line is at or after that
    instant, so an inclusive resume cannot leave a gap. Its only cost is
    re-delivering lines sharing the boundary nanosecond.

    Across a *reconnect* that duplicate is acceptable and is the mechanism
    working: a duplicated line is cosmetic, a missing one is the one being
    looked for. Within a single open stream it is not, because the poll loop
    would re-deliver the boundary line on every pass. So the lines already
    emitted at the current instant are remembered, and only for that instant --
    the set resets as soon as the cursor advances, so it cannot grow.
    """

    def __init__(self) -> None:
        self.ns: int | None = None
        self._delivered_at_ns: set[str] = set()

    def should_emit(self, entry: LogEntry) -> bool:
        ts = int(entry.timestamp_ns)
        if self.ns is None:
            return True
        if ts < self.ns:
            return False
        if ts == self.ns and entry.line in self._delivered_at_ns:
            return False
        return True

    def advance(self, entry: LogEntry) -> None:
        ts = int(entry.timestamp_ns)
        if self.ns is None or ts > self.ns:
            self.ns = ts
            self._delivered_at_ns = {entry.line}
        else:
            self._delivered_at_ns.add(entry.line)


async def fetch_initial(
    client: LokiQueryClient,
    target: LogTarget,
    *,
    tail: int,
    resume_ns: int | None,
    settings: CaelusSettings,
) -> list[LogEntry]:
    """The first batch, fetched **before** the response starts.

    Deliberately not inside the generator: a `StreamingResponse` cannot change
    its status code once the first byte is out, and an unreachable store must
    be reported as a platform condition rather than as an empty success. Doing
    this query here is what keeps a 503 available.

    Mind that `direction` differs between the two cases, and that Loki defaults
    to `backward` -- so the resume path is the one that would break silently.
    """
    selector = build_selector(target)
    if resume_ns is not None:
        # Inclusive, forward: everything at or after where the client stopped.
        return await client.aquery_range(
            query=selector, start_ns=resume_ns, limit=tail, direction=DIRECTION_FORWARD
        )
    # A first connect wants the newest `tail` lines, which is a backward query.
    # The window is explicit because Loki's own default is one hour, which
    # would silently return nothing for an application quiet longer than that
    # -- exactly the case a reader is usually investigating.
    now_ns = time.time_ns()
    return await client.aquery_range(
        query=selector,
        start_ns=max(now_ns - settings.log_initial_lookback_seconds * NS_PER_SECOND, 1),
        end_ns=now_ns + 1,
        limit=tail,
        direction=DIRECTION_BACKWARD,
    )


async def stream_log(
    client: LokiQueryClient,
    target: LogTarget,
    *,
    initial: list[LogEntry],
    follow: bool,
    settings: CaelusSettings | None = None,
) -> AsyncIterator[str]:
    """The SSE body: the already-fetched first batch, then the follow loop.

    Holds **no database session**. Everything it needs was resolved under one
    and handed over in `target`, which is what keeps a long-lived stream from
    pinning a connection for its whole life.
    """
    settings = settings or get_settings()
    cursor = _Cursor()

    if target.release_never_ran:
        # Not a silent empty stream: that would be indistinguishable from an
        # application that printed nothing, which is a different claim.
        yield _sse(
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

    for entry in initial:
        if cursor.should_emit(entry):
            yield _log_event(entry)
            cursor.advance(entry)

    if not follow:
        yield _sse(EVENT_END, {"reason": END_COMPLETE})
        return

    selector = build_selector(target)
    batch_limit = settings.log_max_tail_lines
    opened_at = time.monotonic()
    last_write_at = time.monotonic()

    while True:
        await asyncio.sleep(settings.log_poll_interval_seconds)
        now = time.monotonic()

        # Measured from when the stream opened, never from its last line. A
        # quiet application is working normally and must not be cut off for it
        # -- that would put this in a fight with the keepalive, which exists to
        # hold exactly that connection open.
        #
        # What this bounds is how long a *single authorization* keeps serving:
        # the endpoint authorized once and released its session, so a deleted
        # deployment or a revoked account would otherwise be served until the
        # client went away. Ending cleanly with a reason makes the client
        # reconnect, which re-authorizes.
        if now - opened_at >= settings.log_stream_max_lifetime_seconds:
            yield _sse(EVENT_END, {"reason": END_LIFETIME})
            return

        start_ns = cursor.ns if cursor.ns is not None else time.time_ns()
        try:
            entries = await client.aquery_range(
                query=selector,
                start_ns=start_ns,
                limit=batch_limit,
                direction=DIRECTION_FORWARD,
            )
        except LokiException as exc:
            # Mid-stream, so a status code is long gone -- which is precisely
            # the case SSE was chosen for. The caller can tell this from the
            # end of the output.
            logger.warning(
                "Log stream for deployment_id=%s failed mid-stream: %s",
                target.deployment_id,
                exc,
            )
            yield _sse(EVENT_ERROR, {"error": "log_store_unavailable", "message": str(exc)})
            return

        emitted = 0
        for entry in entries:
            if cursor.should_emit(entry):
                yield _log_event(entry)
                cursor.advance(entry)
                emitted += 1

        if emitted:
            last_write_at = now
            batch_limit = settings.log_max_tail_lines
        elif len(entries) >= batch_limit:
            # The pathological case: a full batch that moved nothing, which
            # means `limit` lines all share the cursor's nanosecond. The cursor
            # cannot advance and the loop would spin forever, silently
            # re-fetching the same lines. Raise the limit; if that is already
            # at the ceiling, fail loudly rather than pretend to be following.
            if batch_limit >= settings.log_max_tail_lines * 8:
                logger.error(
                    "Log stream for deployment_id=%s cannot advance: %d lines share "
                    "timestamp %s",
                    target.deployment_id,
                    len(entries),
                    cursor.ns,
                )
                yield _sse(
                    EVENT_ERROR,
                    {
                        "error": "cursor_stalled",
                        "message": (
                            "Too many log lines share a single nanosecond to continue "
                            "following this deployment."
                        ),
                    },
                )
                return
            batch_limit *= 2
            continue

        # A quiet application is working normally; a quiet *platform* has gone
        # away. The keepalive is what lets a client tell them apart, and what
        # keeps every timeout in the path -- the client's, the homelab
        # HAProxy's, Traefik's -- from treating the connection as dead.
        if now - last_write_at >= settings.log_keepalive_seconds:
            yield _keepalive()
            last_write_at = now


# ---------------------------------------------------------------------------
# Concurrency cap
# ---------------------------------------------------------------------------


class StreamLimitExceeded(ValidationException):
    """This user already holds the maximum number of concurrent log streams."""


class _StreamRegistry:
    """Counts open streams per user, in process.

    In-process is correct rather than a shortcut: the API runs `--workers 1`
    (`api/Dockerfile`), so this process is the only one holding streams. The
    limit exists because every *other* endpoint is served from a bounded thread
    pool behind that single worker -- an unbounded number of long-lived streams
    would deny service to the whole API, not merely to this endpoint.
    """

    def __init__(self) -> None:
        self._open: dict[int, int] = {}

    def acquire(self, user_id: int, *, limit: int) -> None:
        current = self._open.get(user_id, 0)
        if current >= limit:
            raise StreamLimitExceeded(
                f"At most {limit} concurrent log streams may be open; close one and retry."
            )
        self._open[user_id] = current + 1

    def release(self, user_id: int) -> None:
        current = self._open.get(user_id, 0)
        if current <= 1:
            self._open.pop(user_id, None)
        else:
            self._open[user_id] = current - 1

    def open_count(self, user_id: int) -> int:
        return self._open.get(user_id, 0)


stream_registry = _StreamRegistry()
