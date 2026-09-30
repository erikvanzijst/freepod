"""The follow loop: keepalives, the advancing cursor, and how a stream ends.

Drives the async generator directly with `asyncio.run` rather than through the
test client. A followed stream never completes on its own, so it cannot be
exercised by a request/response client at all, and doing it this way needs no
`pytest-asyncio` -- which would be a new dependency for one file.
"""

from __future__ import annotations

import asyncio

import pytest

from app.config import CaelusSettings
from app.services import deployment_logs as log_service
from app.services.loki import LogEntry, LokiException


TS1 = "1787066060000000001"
TS2 = "1787066061000000002"
TS3 = "1787066062000000003"
RELEASE = "3f2a9c14-0b6d-4e18-9a77-5c1e8d4b2f60"

TARGET = log_service.LogTarget(
    deployment_id="11111111-1111-1111-1111-111111111111",
    namespace="ns-abc",
    name="app-abc",
)


def _entry(ts, line, release=RELEASE):
    labels = {"namespace": "ns-abc", "instance": "app-abc"}
    if release is not None:
        labels["release_id"] = release
    return LogEntry(timestamp_ns=ts, line=line, labels=labels)


def _settings(**overrides) -> CaelusSettings:
    base = {
        "loki_base_url": "http://loki.invalid:3100",
        "log_poll_interval_seconds": 0.001,
        "log_keepalive_seconds": 0,
        "log_stream_max_lifetime_seconds": 3600,
        "log_max_tail_lines": 4,
        "_env_file": None,
    }
    return CaelusSettings(**{**base, **overrides})


class ScriptedLoki:
    """Replays a list of batches, one per poll, then repeats the last forever."""

    def __init__(self, batches, *, raise_after: int | None = None):
        self.batches = list(batches)
        self.calls = 0
        self.limits: list[int] = []
        self._raise_after = raise_after

    async def aquery_range(self, *, query, start_ns, limit, direction, end_ns=None):
        self.calls += 1
        self.limits.append(limit)
        if self._raise_after is not None and self.calls > self._raise_after:
            raise LokiException("connection reset")
        if self.calls <= len(self.batches):
            return self.batches[self.calls - 1]
        return self.batches[-1] if self.batches else []


def _collect(client, *, initial, settings, follow=True, limit=12, target=TARGET):
    """Pull at most `limit` chunks off the stream, then stop."""

    async def run():
        chunks = []
        agen = log_service.stream_log(
            client, target, initial=initial, follow=follow, settings=settings
        )
        try:
            async for chunk in agen:
                chunks.append(chunk)
                if len(chunks) >= limit:
                    break
        finally:
            await agen.aclose()
        return chunks

    return asyncio.run(run())


def _log_lines(chunks):
    out = []
    for chunk in chunks:
        if "event: log" not in chunk:
            continue
        for line in chunk.splitlines():
            if line.startswith("data: "):
                import json

                out.append(json.loads(line[6:])["line"])
    return out


# ---------------------------------------------------------------------------
# Keepalives
# ---------------------------------------------------------------------------


def test_a_quiet_stream_emits_keepalives_as_comments(client=None):
    """A comment, so it cannot be mistaken for output. `freepod log > app.log`
    across a quiet period must leave no trace in the file."""
    chunks = _collect(
        ScriptedLoki([[]]), initial=[], settings=_settings(), limit=3
    )
    assert chunks, "expected keepalives on a quiet followed stream"
    for chunk in chunks:
        assert chunk.startswith(": ")
        # A comment carries no event and no id, so a stock EventSource ignores
        # it entirely and no cursor can be derived from it.
        assert "event:" not in chunk
        assert "id:" not in chunk


def test_a_quiet_period_does_not_advance_the_resume_point():
    """Advancing from a keepalive would move the resume point past instants at
    which no line was delivered, permanently skipping a line that arrives late
    bearing an earlier timestamp."""
    seen: list[int] = []

    class Recorder(ScriptedLoki):
        async def aquery_range(self, *, query, start_ns, limit, direction, end_ns=None):
            seen.append(start_ns)
            return await super().aquery_range(
                query=query, start_ns=start_ns, limit=limit, direction=direction
            )

    _collect(Recorder([[], [], []]), initial=[_entry(TS1, "first")], settings=_settings(), limit=4)
    assert seen and all(s == int(TS1) for s in seen)


def test_output_resumes_on_the_same_stream_after_a_quiet_period():
    loki = ScriptedLoki([[], [], [_entry(TS2, "awake")], []])
    chunks = _collect(loki, initial=[_entry(TS1, "first")], settings=_settings(), limit=6)
    lines = _log_lines(chunks)
    assert lines[0] == "first"
    assert "awake" in lines
    # And the quiet period in between left keepalives, not blank log events.
    assert any(c.startswith(": ") for c in chunks)


# ---------------------------------------------------------------------------
# The cursor
# ---------------------------------------------------------------------------


def test_the_boundary_line_is_not_redelivered_within_one_stream():
    """Resumption is inclusive, so every poll re-fetches the lines sharing the
    cursor's nanosecond. Emitting them once is right; emitting them on every
    poll would spray a duplicate line every few seconds. The duplicate is only
    acceptable across a *reconnect*, where it is the at-least-once mechanism
    working."""
    loki = ScriptedLoki([[_entry(TS1, "first")], [_entry(TS1, "first")], []])
    chunks = _collect(loki, initial=[_entry(TS1, "first")], settings=_settings(), limit=5)
    # Once, from the initial batch, and never again however many polls run.
    assert _log_lines(chunks).count("first") == 1
    assert loki.calls >= 2


def test_new_lines_after_the_boundary_are_delivered():
    loki = ScriptedLoki([[_entry(TS1, "first"), _entry(TS2, "second")], []])
    chunks = _collect(loki, initial=[_entry(TS1, "first")], settings=_settings(), limit=5)
    assert _log_lines(chunks) == ["first", "second"]


def test_a_second_line_sharing_the_cursor_nanosecond_is_delivered_once():
    """Two lines at one instant: the one already delivered is suppressed, the
    one that is genuinely new is not."""
    batch = [_entry(TS1, "first"), _entry(TS1, "sibling")]
    loki = ScriptedLoki([batch, batch, batch])
    chunks = _collect(loki, initial=[_entry(TS1, "first")], settings=_settings(), limit=6)
    assert _log_lines(chunks) == ["first", "sibling"]


class StuckLoki:
    """A store where every line shares one nanosecond, however many are asked for.

    Honouring `limit` is the point: raising it is the loop's first response to
    a stalled cursor, and the guard only has to give up when even the raised
    limit comes back full.
    """

    def __init__(self, ts=TS1):
        self.ts = ts
        self.limits: list[int] = []

    async def aquery_range(self, *, query, start_ns, limit, direction, end_ns=None):
        self.limits.append(limit)
        return [_entry(self.ts, f"line-{i}") for i in range(limit)]


def test_a_stalled_cursor_raises_the_limit_then_fails_loudly():
    """The pathological case: `limit` lines all sharing the cursor's nanosecond,
    so the cursor cannot advance and the loop would spin forever, silently
    re-fetching. Raising the limit is the first move; giving up loudly is the
    second. Never an infinite quiet spin, and never a stream that pretends to
    still be following."""
    settings = _settings(log_max_tail_lines=4)
    loki = StuckLoki()
    chunks = _collect(loki, initial=[], settings=settings, limit=60)

    # It tried harder before giving up.
    assert max(loki.limits) > settings.log_max_tail_lines
    assert "event: error" in chunks[-1]
    assert "cursor_stalled" in chunks[-1]


def test_a_stall_that_resolves_when_the_limit_is_raised_keeps_following():
    """Raising the limit is a real fix, not just a delay before failing."""

    class ResolvesLoki(StuckLoki):
        async def aquery_range(self, *, query, start_ns, limit, direction, end_ns=None):
            self.limits.append(limit)
            if limit <= 4:
                return [_entry(TS1, f"line-{i}") for i in range(limit)]
            # With headroom, the batch finally contains a later line.
            return [_entry(TS1, "line-0"), _entry(TS2, "moved on")]

    loki = ResolvesLoki()
    chunks = _collect(loki, initial=[], settings=_settings(log_max_tail_lines=4), limit=10)
    assert "moved on" in _log_lines(chunks)
    assert not any("cursor_stalled" in c for c in chunks)


# ---------------------------------------------------------------------------
# How a stream ends
# ---------------------------------------------------------------------------


def test_a_bounded_read_ends_cleanly():
    chunks = _collect(
        ScriptedLoki([]), initial=[_entry(TS1, "only")], settings=_settings(), follow=False
    )
    assert "event: log" in chunks[0]
    assert "event: end" in chunks[-1]
    assert '"reason":"complete"' in chunks[-1]
    # A bounded read issues no follow queries at all.


def test_a_mid_stream_store_failure_is_signalled_before_the_close():
    """The reason SSE was chosen over an unframed body: after the first byte a
    status code is gone, and a truncated body is indistinguishable from the end
    of the output."""
    loki = ScriptedLoki([[]], raise_after=0)
    chunks = _collect(loki, initial=[_entry(TS1, "before")], settings=_settings(), limit=6)
    assert "event: error" in chunks[-1]
    assert "log_store_unavailable" in chunks[-1]


def test_a_stream_is_closed_cleanly_when_it_reaches_its_lifetime():
    """Closed, but not *reported as disconnected*: the client is told why, so
    it resumes from its cursor rather than concluding the application stopped.

    The bound exists to force re-authorization -- the endpoint authorized once
    and released its session -- not to reclaim resources."""
    settings = _settings(log_stream_max_lifetime_seconds=0)
    chunks = _collect(ScriptedLoki([[]]), initial=[], settings=settings, limit=4)
    assert "event: end" in chunks[-1]
    assert '"reason":"lifetime"' in chunks[-1]


def test_a_quiet_application_never_trips_the_lifetime_bound():
    """The regression this replaced: the bound used to be measured from the
    last *log line*, so a healthy application that simply said nothing was cut
    off -- putting it in direct opposition to the keepalive, whose whole job is
    holding that connection open."""
    settings = _settings(log_stream_max_lifetime_seconds=3600)
    chunks = _collect(ScriptedLoki([[]]), initial=[], settings=settings, limit=6)
    # Nothing but keepalives, and the stream is still going.
    assert chunks
    assert all(c.startswith(": ") for c in chunks)
    assert not any("event: end" in c for c in chunks)


def test_the_lifetime_runs_from_the_stream_opening_not_from_the_last_line():
    """A continuously chatty application is capped just the same: output does
    not extend the lifetime, or a busy stream would never re-authorize."""
    settings = _settings(log_stream_max_lifetime_seconds=0)
    chatty = ScriptedLoki([[_entry(TS2, "still talking")], [_entry(TS3, "and again")]])
    chunks = _collect(chatty, initial=[_entry(TS1, "first")], settings=settings, limit=6)
    assert '"reason":"lifetime"' in chunks[-1]


def test_a_release_that_never_ran_ends_with_that_reason_not_silence():
    target = log_service.LogTarget(
        deployment_id="11111111-1111-1111-1111-111111111111",
        namespace="ns-abc",
        name="app-abc",
        release_id=RELEASE,
        release_number=3,
        release_never_ran=True,
    )
    chunks = _collect(
        ScriptedLoki([]), initial=[], settings=_settings(), target=target, follow=True
    )
    assert len(chunks) == 1
    assert '"reason":"release_never_ran"' in chunks[0]
    assert "never ran" in chunks[0]


# ---------------------------------------------------------------------------
# Selector construction
# ---------------------------------------------------------------------------


def test_the_selector_names_only_the_deployment():
    assert log_service.build_selector(TARGET) == (
        '{namespace="ns-abc", instance="app-abc", container!="ssh"}'
    )


def test_the_selector_excludes_the_platform_ssh_sidecar():
    """sshd logs a line per connection and the edge's liveness probe connects
    every few seconds, so without this an idle deployment's log is mostly
    `Connection closed by ...` rather than the application's own output."""
    assert 'container!="ssh"' in log_service.build_selector(TARGET)


def test_a_pinned_selector_adds_the_release_label():
    target = log_service.LogTarget(
        deployment_id="d", namespace="ns-abc", name="app-abc", release_id=RELEASE
    )
    assert log_service.build_selector(target) == (
        f'{{namespace="ns-abc", instance="app-abc", container!="ssh", release_id="{RELEASE}"}}'
    )


def test_label_values_are_quoted_so_a_stray_quote_cannot_escape_the_selector():
    """No value reaching here is client-supplied today -- namespaces and Helm
    release names are generated by the reconciler. Quoting anyway costs nothing
    and means the next caller does not have to know that."""
    target = log_service.LogTarget(deployment_id="d", namespace='ns"} | {x="', name="app")
    selector = log_service.build_selector(target)
    # Every quote inside the value is escaped, so none of them closes the
    # matcher and the injected `}` stays inside the string.
    assert '\\"' in selector
    assert selector.startswith('{namespace="')
    assert selector.endswith('instance="app", container!="ssh"}')
