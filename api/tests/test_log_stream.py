"""The shared follow loop, as seen by a log whose source skips some stored lines.

The pod log renders every line, so its tests never reach the skipping path; the
HTTP access log skips every line that is not a request record, which on the day
the access log switched format is every line before the switch.
"""

from __future__ import annotations

import asyncio
import json

from app.config import CaelusSettings
from app.services import log_stream
from app.services.loki import LogEntry


TS = [str(1787066060000000000 + i * 1_000_000_000) for i in range(8)]


def _entry(ts, line):
    return LogEntry(timestamp_ns=ts, line=line, labels={})


def _render(entry):
    if entry.line.startswith("skip"):
        return None
    return {"ts": entry.timestamp_ns, "line": entry.line}


SOURCE = log_stream.LogSource(selector='{x="y"}', event="request", render=_render, description="test")


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


class ForwardLoki:
    """A store holding `entries`, answering forward queries the way Loki does."""

    def __init__(self, entries):
        self.entries = entries
        self.starts: list[int] = []

    async def aquery_range(self, *, query, start_ns, limit, direction, end_ns=None):
        self.starts.append(start_ns)
        return [e for e in self.entries if int(e.timestamp_ns) >= start_ns][:limit]


def _run(client, *, initial, polls):
    async def run():
        chunks = []
        agen = log_stream.stream(client, SOURCE, initial=initial, follow=True, settings=_settings())
        try:
            async for chunk in agen:
                chunks.append(chunk)
                if len(client.starts) >= polls:
                    break
        finally:
            await agen.aclose()
        return chunks

    return asyncio.run(run())


def _delivered(chunks):
    return [
        json.loads(line[6:])["line"]
        for chunk in chunks
        for line in chunk.splitlines()
        if line.startswith("data: ") and "event: request" in chunk
    ]


def test_a_full_batch_of_skipped_lines_advances_the_cursor():
    stored = [_entry(TS[i], f"skip {i}") for i in range(1, 5)] + [_entry(TS[5], "request")]
    client = ForwardLoki(stored)

    chunks = _run(client, initial=[_entry(TS[0], "request 0")], polls=4)

    assert not any("event: error" in c for c in chunks)
    assert _delivered(chunks) == ["request 0", "request"]
    # The second poll starts at the last skipped line, not back at the first.
    assert client.starts[1] == int(TS[4])


def test_skipped_lines_in_the_first_batch_are_not_delivered():
    client = ForwardLoki([])
    initial = [_entry(TS[0], "skip"), _entry(TS[1], "request 1")]

    chunks = _run(client, initial=initial, polls=1)

    assert _delivered(chunks) == ["request 1"]
    # The first poll resumes from the newest line seen, delivered or not.
    assert client.starts[0] == int(TS[1])


def test_a_bounded_read_of_only_skipped_lines_is_an_empty_stream():
    async def run():
        return [
            chunk
            async for chunk in log_stream.stream(
                ForwardLoki([]), SOURCE, initial=[_entry(TS[0], "skip")], follow=False,
                settings=_settings(),
            )
        ]

    chunks = asyncio.run(run())

    assert chunks == ['event: end\ndata: {"reason":"complete"}\n\n']
