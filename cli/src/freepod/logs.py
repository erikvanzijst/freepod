"""`freepod log` — reading a deployment's application output.

Stream discipline is the opposite of `deploy`'s, and deliberately so. There,
the build log is the platform narrating its progress towards a result, so it
goes to stderr and leaves stdout for the address. Here the log lines **are**
the result: the user asked for them, and they must survive
`freepod log > app.log` and a pipe into `grep`. So lines go to stdout and every
word the client says about itself goes to stderr.

The transport is Server-Sent Events over the existing `ApiClient`, parsed with
`iter_lines()`. No dependency is added: `httpx` is already here, and SSE is a
line format rather than a protocol needing a library.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional, TextIO

import httpx

from . import FreepodError, UsageError
from .api import ApiClient
from .auth import log
from .config import (
    LOG_RECONNECT_ATTEMPTS,
    LOG_RECONNECT_BACKOFF_SECONDS,
    LOG_STREAM_READ_TIMEOUT,
    env_suffix,
)
from .project import find_project_root, load

# Event names the platform emits. A line beginning with ':' is a comment --
# the keepalive -- and is discarded without ever reaching the output.
EVENT_LOG = "log"
EVENT_ERROR = "error"
EVENT_END = "end"

#: Clean endings. `lifetime` is resumable: the platform caps how long one
#: authorization may keep serving, and a follow reconnects straight through it.
END_LIFETIME = "lifetime"
END_COMPLETE = "complete"


class LogStreamInterrupted(FreepodError):
    """The stream ended without the platform saying it was finished."""


@dataclass
class Event:
    """One parsed SSE event."""

    event: str
    data: Dict[str, Any]


# --------------------------------------------------------------------------
# Resolving what to read
# --------------------------------------------------------------------------


def resolve_deployment(root: Path, env_name: str) -> str:
    """The deployment this project points at, for this environment.

    Says so plainly when there is nothing to read rather than guessing from the
    account's other deployments: a wrong guess prints another application's
    output under this project's name, which is worse than an error.
    """
    found = find_project_root(root)
    if found is None:
        raise FreepodError(
            "no Freepod project here — `freepod log` reads the deployment recorded in "
            "`.freepod.json`.\n"
            "  Run it from a project directory, or run `freepod init` to create one."
        )
    project = load(found)
    if project.env != env_name and project.deployment_id:
        # The recorded deployment is minted on another environment. Naming it
        # keeps the pointer legible: a bare "no deployment here" would send the
        # user to `freepod deploy` for a project that already has one.
        raise UsageError(
            f"this project's deployment is on '{project.env}', not on "
            f"'{env_name}'.\n"
            f"  Re-run without --env (or with --env {project.env}) to read it."
        )
    if not project.deployment_id:
        raise FreepodError(
            f"this project has no deployment{env_suffix(env_name)} yet — there is "
            f"nothing to read.\n"
            f"  Run `freepod deploy` first."
        )
    return project.deployment_id


# --------------------------------------------------------------------------
# SSE
# --------------------------------------------------------------------------


def parse_sse(lines: Iterator[str]) -> Iterator[Event]:
    """Turn a line stream into events, discarding keepalives.

    Keepalives leave no trace at all -- not a blank line, not an empty event --
    so a quiet period is invisible in redirected output.
    """
    event_name = "message"
    data_parts: list[str] = []

    for raw in lines:
        line = raw.rstrip("\r")
        if line.startswith(":"):
            # A comment. The platform's keepalive, describing the connection
            # rather than the log; it carries no id and moves no cursor.
            continue
        if line == "":
            if data_parts:
                payload = "\n".join(data_parts)
                data_parts = []
                name, event_name = event_name, "message"
                try:
                    yield Event(event=name, data=json.loads(payload))
                except ValueError:
                    raise FreepodError(
                        f"the platform sent a log event this client cannot parse: "
                        f"{payload[:200]}"
                    ) from None
            else:
                event_name = "message"
            continue
        field, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field == "event":
            event_name = value
        elif field == "data":
            data_parts.append(value)
        # `id` is ignored on purpose: it mirrors the timestamp the event
        # already carries, and tracking two representations of one fact is how
        # they drift apart.


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def format_line(data: Dict[str, Any], *, timestamps: bool) -> str:
    """Render one log event.

    Optional prefixes appear in a fixed order -- `<timestamp> <release> <line>`
    -- so output stays splittable by position however many are enabled. Only
    the timestamp is exposed as a flag today; which release a line came from is
    narrated on stderr when it *changes*, rather than repeated on every line,
    because it is the same value for thousands of consecutive lines and
    prefixing it would be noise in the one stream that must stay clean.

    Timestamps are off by default because many applications already stamp their
    own output, and a second prefix yields a line bearing two dates -- worse
    than none for a reader and worse for anything parsing.
    """
    line = data.get("line", "")
    prefixes = []
    if timestamps:
        prefixes.append(format_timestamp(data.get("ts")))
    return " ".join(prefixes + [line]) if prefixes else line


def format_timestamp(ts: Optional[str]) -> str:
    """Render a nanosecond timestamp as UTC, without ever touching a float.

    `int(...)`, never `float(...)`: the value is ~1.76e18 against a double's
    exact-integer ceiling of ~9.01e15, so any float round trip silently
    corrupts both the rendered time and the resume point.
    """
    if not ts:
        return "-"
    try:
        nanos = int(ts)
    except (TypeError, ValueError):
        return "-"
    seconds, remainder = divmod(nanos, 1_000_000_000)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(seconds))
    return f"{stamp}.{remainder:09d}Z"


# --------------------------------------------------------------------------
# Streaming
# --------------------------------------------------------------------------


@dataclass
class Cursor:
    """What the client must remember across a reconnect.

    Only the timestamp of the last event received -- the same field
    `--timestamps` renders. Tracking a separate resume value would mean two
    representations of one fact, which is how what is displayed and what is
    resumed from come to disagree.
    """

    ts: Optional[str] = None
    lines: int = 0
    #: Every release seen so far, so a rollover is announced once per release
    #: rather than prefixed onto every line. A *set*, not the last value seen:
    #: during a rollout the old and new pods write concurrently and the
    #: platform returns both interleaved, so comparing against the previous
    #: line alone announces the same two releases over and over. Survives a
    #: reconnect, so a resume does not re-announce what it was already
    #: following. Bounded in practice -- one entry per deploy.
    seen_releases: set = field(default_factory=set)


def _timeout(follow: bool) -> httpx.Timeout:
    """Read timeout: bounded for a finite read, keepalive-scaled for a follow.

    A followed stream must not carry the client's ordinary request timeout --
    httpx applies it per read, so it would disconnect any application quiet for
    longer than an ordinary request should take. What bounds a follow is the
    platform's silence, not the application's.
    """
    read = LOG_STREAM_READ_TIMEOUT if follow else None
    return httpx.Timeout(connect=15.0, read=read, write=15.0, pool=15.0)


def stream_once(
    api: ApiClient,
    user_id: int,
    deployment_id: str,
    cursor: Cursor,
    *,
    follow: bool,
    tail: Optional[int] = None,
    release: Optional[int] = None,
    timestamps: bool = False,
    out: TextIO,
    say: Callable[[str], None],
) -> Optional[str]:
    """Consume one connection. Returns the platform's end reason, or None if it
    stopped without one.

    A None return is an *interruption*, not an ending: the platform says why it
    finished when it finishes on purpose.
    """
    params: Dict[str, Any] = {}
    if follow:
        params["follow"] = "true"
    if tail is not None:
        params["tail"] = str(tail)
    if release is not None:
        params["release"] = str(release)
    if cursor.ts is not None:
        # Inclusive, and the platform's business: a line sharing this instant
        # may arrive twice, which is the mechanism working. Suppressing
        # duplicates here would risk discarding a line that was genuinely new.
        params["since"] = cursor.ts

    path = f"/api/users/{user_id}/deployments/{deployment_id}/log"
    with api.stream("GET", path, params=params, timeout=_timeout(follow)) as response:
        if response.status_code == 503:
            raise FreepodError(
                f"the platform cannot reach its log store, so it cannot say what this "
                f"application printed. This is a platform condition, not a silent "
                f"application.\n  {_detail(response)}"
            )
        if response.status_code == 404:
            raise FreepodError(
                f"no such deployment or release{env_suffix(api.env.name)}.\n"
                f"  {_detail(response)}"
            )
        if not response.is_success:
            raise FreepodError(
                f"could not read the log: HTTP {response.status_code} "
                f"{_detail(response)}"
            )

        for event in parse_sse(response.iter_lines()):
            if event.event == EVENT_LOG:
                release_id = event.data.get("release")
                if release_id and release_id not in cursor.seen_releases:
                    # A rollover: the user is watching an application, not a
                    # container, so a redeploy shows up here rather than
                    # ending the stream. On stderr -- it is the client
                    # describing what it is doing, not the application's output.
                    # The first release seen is what the stream opened on and
                    # is not a rollover.
                    if cursor.seen_releases:
                        say(f"Now following release {release_id}.")
                    cursor.seen_releases.add(release_id)
                print(format_line(event.data, timestamps=timestamps), file=out, flush=True)
                ts = event.data.get("ts")
                if ts:
                    cursor.ts = ts
                cursor.lines += 1
            elif event.event == EVENT_ERROR:
                # Mid-stream, so the status code is long gone -- which is the
                # reason the platform frames this rather than just closing.
                raise FreepodError(
                    f"the platform interrupted the stream: "
                    f"{event.data.get('message') or event.data.get('error')}"
                )
            elif event.event == EVENT_END:
                return str(event.data.get("reason") or "")
    return None


def _detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip()[:300]
    if isinstance(payload, dict) and "detail" in payload:
        return str(payload["detail"])
    return response.text.strip()[:300]


def follow_stream(
    api: ApiClient,
    user_id: int,
    deployment_id: str,
    *,
    tail: Optional[int],
    release: Optional[int],
    timestamps: bool,
    out: TextIO,
    say: Callable[[str], None],
    attempts: int = LOG_RECONNECT_ATTEMPTS,
    backoff: float = LOG_RECONNECT_BACKOFF_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> Cursor:
    """Follow a deployment, reconnecting from the cursor rather than the present.

    Restarting at the present would silently lose everything written during the
    outage -- which is when the interesting output tends to happen.
    """
    cursor = Cursor()
    failures = 0
    first = True

    def give_up(exc: object) -> LogStreamInterrupted:
        return LogStreamInterrupted(
            f"the log stream was interrupted and could not be re-established after "
            f"{attempts} attempts ({exc}).\n"
            f"  This says nothing about the application, which may still be running — "
            f"try again, or check `freepod status`."
        )

    while True:
        delivered = cursor.lines
        try:
            reason = stream_once(
                api, user_id, deployment_id, cursor,
                # The tail is a *first connect* concern. Re-requesting it on a
                # reconnect would reprint what the user has already read.
                follow=True, tail=tail if first else None, release=release,
                timestamps=timestamps, out=out, say=say,
            )
        except (httpx.HTTPError, LogStreamInterrupted) as exc:
            failures += 1
            if failures > attempts:
                raise give_up(exc) from None
            delay = backoff * (2 ** (failures - 1))
            # Never silent: a gap in a followed stream that nobody mentioned
            # reads as the application having gone quiet.
            say(f"Stream interrupted ({exc}); reconnecting in {delay:.0f}s...")
            sleep(delay)
            first = False
            continue

        first = False
        # Progress resets the budget. A long follow that drops every few hours
        # and resumes cleanly each time is working, not failing, and counting
        # those cumulatively would eventually abandon a healthy stream.
        if cursor.lines > delivered:
            failures = 0

        if reason == END_LIFETIME:
            # The platform caps how long one authorization keeps serving.
            # Expected and resumable, so reconnect straight through it without
            # saying anything: the user asked to watch an application, not a
            # connection.
            continue

        if reason is not None:
            # The platform said it had finished — `complete`, or a release
            # that never ran. That is an answer, not an interruption.
            return cursor

        # No end event: the response ended without the platform saying it was
        # done, so something between here and there dropped it. In follow mode
        # that is an interruption to resume from, not the end of the log.
        failures += 1
        if failures > attempts:
            raise give_up("the stream kept ending without the platform saying it had finished")
        delay = backoff * (2 ** (failures - 1))
        say(f"Stream ended unexpectedly; reconnecting in {delay:.0f}s...")
        sleep(delay)


# --------------------------------------------------------------------------
# The command
# --------------------------------------------------------------------------


def run(
    api: ApiClient,
    env_name: str,
    *,
    root: Path,
    follow: bool = False,
    tail: Optional[int] = None,
    release: Optional[int] = None,
    timestamps: bool = False,
    out: Optional[TextIO] = None,
    say: Callable[[str], None] = log,
) -> int:
    """Stream the project's deployment log. Returns an exit code."""
    out = out if out is not None else sys.stdout
    deployment_id = resolve_deployment(root, env_name)
    user_id = api.me()["id"]

    if release is not None:
        say(f"Reading release {release} of deployment {deployment_id}.")

    if follow:
        cursor = follow_stream(
            api, user_id, deployment_id,
            tail=tail, release=release, timestamps=timestamps, out=out, say=say,
        )
    else:
        cursor = Cursor()
        stream_once(
            api, user_id, deployment_id, cursor,
            follow=False, tail=tail, release=release,
            timestamps=timestamps, out=out, say=say,
        )

    if cursor.lines == 0:
        # An empty result is an answer, and saying so is what keeps it legible
        # as one rather than as a broken command. On stderr, so a redirected
        # stdout stays byte-for-byte the application's own output -- which here
        # is correctly empty.
        say("The application has produced no output.")
    return 0
