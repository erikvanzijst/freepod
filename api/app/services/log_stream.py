"""Streaming a log out of the store: the machinery every log endpoint shares.

Which lines a caller may see is decided elsewhere -- `deployment_logs.py` for an
application's output, `http_logs.py` for its HTTP access log. Each describes
itself as a `LogSource`: a selector it built from an authorized row, the SSE
event name its lines go out under, and how one stored line becomes an event
payload. This module owns everything after that: the resume point, the first
batch, the follow loop, keepalives, and the per-user stream cap.

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
from typing import AsyncIterator, Callable

from app.config import CaelusSettings, get_settings
from app.services.errors import ValidationException
from app.services.loki import (
    DIRECTION_BACKWARD,
    DIRECTION_FORWARD,
    LogEntry,
    LokiException,
    LokiQueryClient,
)

logger = logging.getLogger(__name__)

NS_PER_SECOND = 1_000_000_000
# A nanosecond timestamp is a uint64. The lower bound rejects a value in
# seconds or milliseconds -- a plausible client mistake that would otherwise
# silently ask for everything since 1970 -- by requiring it to be at least
# 2001-09-09, the point where second-resolution epochs stopped being 9 digits.
MIN_TIMESTAMP_NS = 1_000_000_000 * NS_PER_SECOND
MAX_TIMESTAMP_NS = 2**64 - 1


@dataclass(frozen=True)
class LogSource:
    """One log, as the follow loop needs it."""

    selector: str
    # The SSE event name each delivered line goes out under.
    event: str
    # A stored line as an event payload, or None for a line that is not one of
    # this log's records. A skipped line still moves the cursor past it.
    render: Callable[[LogEntry], dict | None]
    # Names the stream in the platform's own logs; never sent to the client.
    description: str


# ---------------------------------------------------------------------------
# Client-supplied values
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


def check_lookback(seconds: int | None, settings: CaelusSettings) -> int | None:
    """Refuse a window the store cannot answer, rather than quietly shortening it.

    The bound is the initial lookback, which is set to the store's retention:
    a longer window would read as a promise of history that does not exist.
    """
    if seconds is None:
        return None
    limit = settings.log_initial_lookback_seconds
    if seconds > limit:
        raise ValidationException(
            f"A log can be read at most {_describe_seconds(limit)} back; "
            f"{_describe_seconds(seconds)} was requested."
        )
    return seconds


def _describe_seconds(seconds: int) -> str:
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if seconds % size == 0:
            count = seconds // size
            return f"{count} {unit}{'' if count == 1 else 's'}"
    return f"{seconds} seconds"


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

EVENT_ERROR = "error"
EVENT_END = "end"

# Clean-ending reasons, so a client can tell "that is all there is" from
# "the platform gave up" without parsing prose. `lifetime` in particular is a
# *resumable* ending: the client reconnects from its cursor and loses nothing.
END_COMPLETE = "complete"
END_LIFETIME = "lifetime"


def sse(event: str, data: dict, *, event_id: str | None = None) -> str:
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


def _event(source: LogSource, entry: LogEntry) -> str | None:
    """One line, or None when the source does not count it as one of its own.

    The payload's `ts` is mirrored into `id:` so a stock `EventSource` gets
    `Last-Event-ID` for free; the contract names the `ts` field.
    """
    data = source.render(entry)
    if data is None:
        return None
    return sse(source.event, data, event_id=entry.timestamp_ns)


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

    A line the source skips advances the cursor exactly like one it delivers.
    Otherwise a run of skipped lines at the cursor would be fetched again on
    every poll, and a full batch of them would look like a stalled cursor.
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
    selector: str,
    *,
    tail: int,
    resume_ns: int | None,
    settings: CaelusSettings,
    lookback_seconds: int | None = None,
) -> list[LogEntry]:
    """The first batch, fetched **before** the response starts.

    Deliberately not inside the generator: a `StreamingResponse` cannot change
    its status code once the first byte is out, and an unreachable store must
    be reported as a platform condition rather than as an empty success. Doing
    this query here is what keeps a 503 available.

    Mind that `direction` differs between the two cases, and that Loki defaults
    to `backward` -- so the resume path is the one that would break silently.
    """
    if resume_ns is not None:
        # Inclusive, forward: everything at or after where the client stopped.
        # A resume point wins over a window: the window was the first connect's
        # question, and the client has already been answered it.
        return await client.aquery_range(
            query=selector, start_ns=resume_ns, limit=tail, direction=DIRECTION_FORWARD
        )
    # A first connect wants the newest `tail` lines, which is a backward query.
    # The window is explicit because Loki's own default is one hour, which
    # would silently return nothing for an application quiet longer than that
    # -- exactly the case a reader is usually investigating. A requested window
    # only narrows it, so "the newest `tail` within the window" falls out of
    # the same query.
    lookback = lookback_seconds or settings.log_initial_lookback_seconds
    now_ns = time.time_ns()
    return await client.aquery_range(
        query=selector,
        start_ns=max(now_ns - lookback * NS_PER_SECOND, 1),
        end_ns=now_ns + 1,
        limit=tail,
        direction=DIRECTION_BACKWARD,
    )


async def stream(
    client: LokiQueryClient,
    source: LogSource,
    *,
    initial: list[LogEntry],
    follow: bool,
    settings: CaelusSettings | None = None,
) -> AsyncIterator[str]:
    """The SSE body: the already-fetched first batch, then the follow loop.

    Holds **no database session**. Everything it needs was resolved under one
    and handed over in `source`, which is what keeps a long-lived stream from
    pinning a connection for its whole life.
    """
    settings = settings or get_settings()
    cursor = _Cursor()

    for entry in initial:
        if cursor.should_emit(entry):
            event = _event(source, entry)
            if event is not None:
                yield event
            cursor.advance(entry)

    if not follow:
        yield sse(EVENT_END, {"reason": END_COMPLETE})
        return

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
            yield sse(EVENT_END, {"reason": END_LIFETIME})
            return

        start_ns = cursor.ns if cursor.ns is not None else time.time_ns()
        try:
            entries = await client.aquery_range(
                query=source.selector,
                start_ns=start_ns,
                limit=batch_limit,
                direction=DIRECTION_FORWARD,
            )
        except LokiException as exc:
            # Mid-stream, so a status code is long gone -- which is precisely
            # the case SSE was chosen for. The caller can tell this from the
            # end of the output.
            logger.warning("Log stream for %s failed mid-stream: %s", source.description, exc)
            yield sse(EVENT_ERROR, {"error": "log_store_unavailable", "message": str(exc)})
            return

        emitted = 0
        advanced = 0
        for entry in entries:
            if cursor.should_emit(entry):
                event = _event(source, entry)
                if event is not None:
                    yield event
                    emitted += 1
                cursor.advance(entry)
                advanced += 1

        if emitted:
            last_write_at = now
        if advanced:
            batch_limit = settings.log_max_tail_lines
        elif len(entries) >= batch_limit:
            # The pathological case: a full batch that moved nothing, which
            # means `limit` lines all share the cursor's nanosecond. The cursor
            # cannot advance and the loop would spin forever, silently
            # re-fetching the same lines. Raise the limit; if that is already
            # at the ceiling, fail loudly rather than pretend to be following.
            if batch_limit >= settings.log_max_tail_lines * 8:
                logger.error(
                    "Log stream for %s cannot advance: %d lines share timestamp %s",
                    source.description,
                    len(entries),
                    cursor.ns,
                )
                yield sse(
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
    """Counts open streams per user, in process, whichever log they read.

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
