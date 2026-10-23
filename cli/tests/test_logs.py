"""`freepod log`: what it reads, where its output goes, and how it survives silence."""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import httpx
import pytest

from freepod import EXIT_USAGE, FreepodError, UsageError
from freepod.cli import main
from freepod.logs import (
    Cursor,
    LogStreamInterrupted,
    follow_stream,
    format_line,
    format_request,
    format_timestamp,
    parse_since,
    parse_sse,
    resolve_deployment,
    run,
    stream_once,
)
from freepod.project import Project

from conftest import json_response

TS1 = "1787066060123456789"
TS2 = "1787066061987654321"
RELEASE = "3f2a9c14-0b6d-4e18-9a77-5c1e8d4b2f60"
DEPLOYMENT = "07744ba8-8307-4bb1-9e69-9367caf4f5f9"


def sse(*blocks: str) -> bytes:
    return ("\n\n".join(blocks) + "\n\n").encode("utf-8")


def log_event(ts: str, line: str, release=RELEASE) -> str:
    data = json.dumps({"ts": ts, "line": line, "release": release})
    return f"id: {ts}\nevent: log\ndata: {data}"


def end(reason: str = "complete") -> str:
    return f'event: end\ndata: {json.dumps({"reason": reason})}'


def stream_response(body: bytes, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status, content=body, headers={"Content-Type": "text/event-stream"}
    )


def project_at(tmp_path: Path, *, env="prod", deployment=DEPLOYMENT) -> Path:
    Project(
        root=tmp_path,
        env=env,
        deployment={"id": deployment, "name": "custom-d8dtx4"} if deployment else None,
        user_values={"hostname": "myapp.freepod.eu"},
    ).save()
    return tmp_path


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def test_keepalives_leave_no_trace():
    """Not a blank line, not an empty event. A quiet period must be invisible
    in `freepod log > app.log`."""
    body = ": keepalive\n\n" + log_event(TS1, "hello") + "\n\n: keepalive\n\n" + end() + "\n\n"
    events = list(parse_sse(iter(body.split("\n"))))
    assert [e.event for e in events] == ["log", "end"]


def test_an_event_id_is_ignored_in_favour_of_the_timestamp_field():
    """Two representations of one fact are how they come to disagree; the
    contract names the `ts` field."""
    events = list(parse_sse(iter(sse(log_event(TS1, "hi")).decode().split("\n"))))
    assert events[0].data["ts"] == TS1


def test_a_malformed_event_is_reported_not_silently_dropped():
    body = "event: log\ndata: {not json\n\n"
    with pytest.raises(FreepodError, match="cannot parse"):
        list(parse_sse(iter(body.split("\n"))))


# --------------------------------------------------------------------------
# Timestamps (task 8.6 / 8.7)
# --------------------------------------------------------------------------


def test_a_nanosecond_timestamp_round_trips_without_a_float():
    """~1.76e18 against a double's exact-integer ceiling of ~9.01e15. Going
    through a float corrupts this silently, which is the whole reason the
    platform sends it as a string."""
    rendered = format_timestamp(TS1)
    assert rendered == "2026-08-18T15:14:20.123456789Z"
    # Every digit survives; the float route does not.
    assert rendered.split(".")[1][:9] == TS1[-9:]
    assert int(float(TS1)) != int(TS1)


def test_timestamps_are_off_by_default():
    """Many applications already stamp their own output; a second prefix yields
    a line bearing two dates."""
    data = {"ts": TS1, "line": "hello", "release": RELEASE}
    assert format_line(data, timestamps=False) == "hello"
    assert format_line(data, timestamps=True).endswith(" hello")
    assert format_line(data, timestamps=True).startswith("2026-")


def test_the_line_shape_does_not_differ_between_modes(make_api, tmp_path):
    """Differently shaped lines per mode is exactly what a downstream pipe
    relies on not happening."""
    body = sse(log_event(TS1, "hello"), end())
    api, _, _ = make_api(lambda request: stream_response(body))
    bounded, followed = io.StringIO(), io.StringIO()

    stream_once(api, 7, DEPLOYMENT, Cursor(), follow=False, out=bounded, say=lambda _m: None)
    stream_once(api, 7, DEPLOYMENT, Cursor(), follow=True, out=followed, say=lambda _m: None)

    assert bounded.getvalue() == followed.getvalue() == "hello\n"


# --------------------------------------------------------------------------
# Resolving the deployment (task 8.1)
# --------------------------------------------------------------------------


def test_outside_a_project_it_says_so_rather_than_guessing(tmp_path):
    with pytest.raises(FreepodError, match="no Freepod project"):
        resolve_deployment(tmp_path, "prod")


def test_a_project_with_no_deployment_says_so(tmp_path):
    project_at(tmp_path, deployment=None)
    with pytest.raises(FreepodError, match="no deployment"):
        resolve_deployment(tmp_path, "prod")


def test_a_project_for_another_environment_is_named(tmp_path):
    project_at(tmp_path, env="dev")
    with pytest.raises(FreepodError, match="deployment is on 'dev'"):
        resolve_deployment(tmp_path, "prod")


def test_a_project_for_another_environment_without_a_deployment_says_so(tmp_path):
    """No pointer means nothing is minted on either environment, so the
    ordinary "nothing to read" answer is the right one."""
    project_at(tmp_path, env="dev", deployment=None)
    with pytest.raises(FreepodError, match="no deployment"):
        resolve_deployment(tmp_path, "prod")


def test_a_project_directory_needs_no_arguments(tmp_path):
    project_at(tmp_path)
    assert resolve_deployment(tmp_path, "prod") == DEPLOYMENT


# --------------------------------------------------------------------------
# The query the client sends
# --------------------------------------------------------------------------


def test_a_resume_sends_the_last_timestamp_inclusively(make_api):
    api, recorder, _ = make_api(lambda request: stream_response(sse(end())))
    stream_once(
        api, 7, DEPLOYMENT, Cursor(ts=TS1),
        follow=False, out=io.StringIO(), say=lambda _m: None,
    )
    assert recorder.requests[0].url.params["since"] == TS1


def test_a_first_read_sends_no_resume_point(make_api):
    api, recorder, _ = make_api(lambda request: stream_response(sse(end())))
    stream_once(api, 7, DEPLOYMENT, Cursor(), follow=False, out=io.StringIO(), say=lambda _m: None)
    assert "since" not in recorder.requests[0].url.params


def test_release_pinning_is_passed_through(make_api):
    api, recorder, _ = make_api(lambda request: stream_response(sse(end())))
    stream_once(
        api, 7, DEPLOYMENT, Cursor(), follow=False, release=5,
        out=io.StringIO(), say=lambda _m: None,
    )
    assert recorder.requests[0].url.params["release"] == "5"


# --------------------------------------------------------------------------
# Failure reporting (task 8.9)
# --------------------------------------------------------------------------


def test_an_unavailable_log_store_is_not_reported_as_a_silent_application(make_api):
    api, _, _ = make_api(
        lambda request: json_response(503, {"detail": "Log store is unavailable: refused"})
    )
    with pytest.raises(FreepodError) as excinfo:
        stream_once(api, 7, DEPLOYMENT, Cursor(), follow=False, out=io.StringIO(), say=lambda _m: None)
    message = str(excinfo.value)
    assert "platform condition" in message
    assert "not a silent application" in message


def test_a_mid_stream_error_is_distinguished_from_the_end_of_output(make_api):
    """After the first byte a status code is gone, which is why the platform
    frames this rather than just closing the connection."""
    body = sse(
        log_event(TS1, "before"),
        'event: error\ndata: {"error":"log_store_unavailable","message":"reset"}',
    )
    api, _, _ = make_api(lambda request: stream_response(body))
    out = io.StringIO()
    with pytest.raises(FreepodError, match="interrupted the stream"):
        stream_once(api, 7, DEPLOYMENT, Cursor(), follow=False, out=out, say=lambda _m: None)
    # What did arrive was still printed.
    assert out.getvalue() == "before\n"


def test_a_genuinely_silent_application_is_reported_on_stderr(make_api, tmp_path):
    project_at(tmp_path)
    api, _, _ = make_api(
        lambda request: json_response(200, {"id": 7})
        if request.url.path == "/api/me"
        else stream_response(sse(end()))
    )
    said, out = [], io.StringIO()

    code = run(api, "prod", root=tmp_path, out=out, say=said.append)

    assert code == 0
    assert out.getvalue() == ""              # stdout stays byte-for-byte empty
    assert any("no output" in line for line in said)


# --------------------------------------------------------------------------
# Reconnection (task 8.5)
# --------------------------------------------------------------------------


def test_a_follow_resumes_from_the_cursor_after_an_interruption(make_api):
    """Restarting at the present would lose exactly the output written during
    the outage, which is when the interesting output tends to happen."""
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return stream_response(sse(log_event(TS1, "before")))
        if attempts["n"] == 2:
            raise httpx.ReadError("connection reset")
        return stream_response(sse(log_event(TS2, "after"), end()))

    api, recorder, _ = make_api(handler)
    out, said = io.StringIO(), []

    cursor = follow_stream(
        api, 7, DEPLOYMENT, tail=None, release=None, timestamps=False,
        out=out, say=said.append, sleep=lambda _s: None,
    )

    assert out.getvalue() == "before\nafter\n"
    # The reconnect asked to continue from the last line seen, not from now.
    assert recorder.requests[-1].url.params["since"] == TS1
    assert cursor.ts == TS2
    # And it was never silent about the gap.
    assert any("reconnect" in line.lower() for line in said)


def test_the_tail_is_only_requested_on_the_first_connect(make_api):
    """A reconnect that re-requested the tail would reprint what the user has
    already seen."""
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return stream_response(sse(log_event(TS1, "x")))
        return stream_response(sse(end()))

    api, recorder, _ = make_api(handler)
    follow_stream(
        api, 7, DEPLOYMENT, tail=50, release=None, timestamps=False,
        out=io.StringIO(), say=lambda _m: None, sleep=lambda _s: None,
    )
    assert recorder.requests[0].url.params["tail"] == "50"
    assert "tail" not in recorder.requests[-1].url.params


def test_exhausted_reconnects_report_an_interruption_not_an_ending(make_api):
    def handler(request):
        raise httpx.ReadError("still down")

    api, _, _ = make_api(handler)
    with pytest.raises(LogStreamInterrupted) as excinfo:
        follow_stream(
            api, 7, DEPLOYMENT, tail=None, release=None, timestamps=False,
            out=io.StringIO(), say=lambda _m: None, attempts=2, sleep=lambda _s: None,
        )
    message = str(excinfo.value)
    assert "interrupted" in message
    # Must not imply the application stopped.
    assert "says nothing about the application" in message


def test_a_lifetime_ending_reconnects_without_bothering_the_user(make_api):
    """The platform caps how long one authorization keeps serving. A follow
    should sail through it: the user asked to watch an application, not a
    connection."""
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return stream_response(sse(log_event(TS1, "before"), end("lifetime")))
        return stream_response(sse(log_event(TS2, "after"), end("complete")))

    api, recorder, _ = make_api(handler)
    out, said = io.StringIO(), []

    follow_stream(
        api, 7, DEPLOYMENT, tail=None, release=None, timestamps=False,
        out=out, say=said.append, sleep=lambda _s: None,
    )

    assert out.getvalue() == "before\nafter\n"
    assert recorder.requests[-1].url.params["since"] == TS1
    # Nothing alarming was said about a routine, resumable ending.
    assert not any("interrupt" in line.lower() for line in said)


def test_a_duplicated_line_after_a_reconnect_is_printed_not_suppressed(make_api):
    """Resumption is at-least-once. Suppressing lines to deduplicate risks
    discarding one that was genuinely new."""
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return stream_response(sse(log_event(TS1, "boundary")))
        return stream_response(sse(log_event(TS1, "boundary"), end()))

    api, _, _ = make_api(handler)
    out = io.StringIO()
    follow_stream(
        api, 7, DEPLOYMENT, tail=None, release=None, timestamps=False,
        out=out, say=lambda _m: None, sleep=lambda _s: None,
    )
    assert out.getvalue() == "boundary\nboundary\n"


# --------------------------------------------------------------------------
# Stream discipline (task 8.4 / 8.10)
# --------------------------------------------------------------------------


def test_redirected_output_carries_the_application_and_nothing_the_client_added(
    make_api, tmp_path
):
    """`freepod log > app.log` must contain the application's lines only.

    The opposite split from `deploy`, and deliberately: there the build log is
    the platform narrating its progress towards a result, so stdout is left for
    the address. Here the lines *are* the result.
    """
    project_at(tmp_path)
    body = sse(
        log_event(TS1, "line one"),
        log_event(TS2, "line two"),
        end(),
    )
    api, _, _ = make_api(
        lambda request: json_response(200, {"id": 7})
        if request.url.path == "/api/me"
        else stream_response(body)
    )
    out, said = io.StringIO(), []

    run(api, "prod", root=tmp_path, release=3, out=out, say=said.append)

    assert out.getvalue() == "line one\nline two\n"
    # The release notice is narration and belongs on stderr.
    assert any("release 3" in line for line in said)
    assert "release 3" not in out.getvalue()


def test_a_quiet_period_leaves_no_keepalive_residue_in_the_output(make_api):
    """A quiet application is working normally, and a redirected stream taken
    across one must be indistinguishable from a busy stream's."""
    body = (
        ": keepalive\n\n"
        ": keepalive\n\n"
        + log_event(TS1, "awake") + "\n\n"
        ": keepalive\n\n"
        + end() + "\n\n"
    ).encode("utf-8")
    api, _, _ = make_api(lambda request: stream_response(body))
    out = io.StringIO()

    stream_once(api, 7, DEPLOYMENT, Cursor(), follow=True, out=out, say=lambda _m: None)

    assert out.getvalue() == "awake\n"


def test_the_command_adds_no_package_dependency():
    """The whole point of SSE over a WebSocket: `httpx` is already here and a
    line format needs no library.

    Asserted against the *installed distribution's* metadata rather than by
    parsing `pyproject.toml`. It is the stronger claim -- what the built wheel
    declares is what a user actually installs -- and `importlib.metadata` is
    stdlib on every Python this package supports, where `tomllib` is 3.11+ and
    would fail the 3.9 leg of CI.
    """
    import importlib.metadata

    declared = importlib.metadata.requires("freepod") or []
    names = sorted(re.split(r"[\s><=!~;\[]", spec)[0] for spec in declared)
    assert names == ["click", "httpx", "pathspec"]


def test_a_rollover_is_announced_on_stderr_and_never_prefixed_onto_a_line(make_api):
    """`-f` follows the application across a redeploy, so the release changes
    mid-stream. Saying so once keeps stdout clean; prefixing it onto thousands
    of consecutive identical lines would not."""
    body = sse(
        log_event(TS1, "old release", release="rel-a"),
        log_event(TS2, "new release", release="rel-b"),
        end(),
    )
    api, _, _ = make_api(lambda request: stream_response(body))
    out, said = io.StringIO(), []

    stream_once(api, 7, DEPLOYMENT, Cursor(), follow=True, out=out, say=said.append)

    assert out.getvalue() == "old release\nnew release\n"
    assert [line for line in said if "rel-b" in line]
    # The first release is not announced -- there was no rollover yet.
    assert not [line for line in said if "rel-a" in line]


def test_interleaved_releases_during_a_rollout_announce_each_once(make_api):
    """During a rollout the old and new pods write at the same time and the
    platform returns both, interleaved. Comparing each line against the one
    before it announced the same two releases over and over -- observed on dev
    against a real redeploy."""
    body = sse(
        log_event(TS1, "old 1", release="rel-a"),
        log_event(TS1, "new 1", release="rel-b"),
        log_event(TS2, "old 2", release="rel-a"),
        log_event(TS2, "new 2", release="rel-b"),
        log_event(TS2, "old 3", release="rel-a"),
        end(),
    )
    api, _, _ = make_api(lambda request: stream_response(body))
    out, said = io.StringIO(), []

    stream_once(api, 7, DEPLOYMENT, Cursor(), follow=True, out=out, say=said.append)

    # Every line is printed, in the order the platform sent them.
    assert out.getvalue().splitlines() == ["old 1", "new 1", "old 2", "new 2", "old 3"]
    # And the rollover is mentioned exactly once.
    assert len([line for line in said if "Now following" in line]) == 1
    assert "rel-b" in said[0]


def test_a_resume_does_not_re_announce_the_release_it_was_already_following(make_api):
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return stream_response(sse(log_event(TS1, "a", release="rel-a")))
        return stream_response(sse(log_event(TS2, "b", release="rel-a"), end()))

    api, _, _ = make_api(handler)
    said = []
    follow_stream(
        api, 7, DEPLOYMENT, tail=None, release=None, timestamps=False,
        out=io.StringIO(), say=said.append, sleep=lambda _s: None,
    )
    assert not [line for line in said if "Now following" in line]


# --------------------------------------------------------------------------
# --since
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, seconds", [("30s", 30), ("15m", 900), ("2h", 7200), ("3d", 259200), ("14d", 1209600)]
)
def test_since_accepts_a_whole_number_and_a_unit(text, seconds):
    assert parse_since(text) == seconds


@pytest.mark.parametrize("text", ["1w", "90", "0m", "1.5h", "-1h", "h", "1 h", ""])
def test_since_refuses_anything_else(text):
    with pytest.raises(UsageError, match="30s, 15m, 2h, 3d"):
        parse_since(text)


def test_a_malformed_since_is_refused_before_anything_is_sent(stub_api, capsys):
    def handler(request):
        raise AssertionError(f"no request should be made, got {request.url}")

    stub_api(handler)
    assert main(["log", "--since", "1w"]) == EXIT_USAGE
    assert "--since" in capsys.readouterr().err


def test_a_window_is_sent_as_lookback_seconds(make_api):
    api, recorder, _ = make_api(lambda request: stream_response(sse(end())))
    stream_once(
        api, 7, DEPLOYMENT, Cursor(), follow=False, lookback=3600,
        out=io.StringIO(), say=lambda _m: None,
    )
    assert recorder.requests[0].url.params["lookback"] == "3600"


def test_a_reconnect_resumes_from_the_cursor_and_does_not_resend_the_window(make_api):
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return stream_response(sse(log_event(TS1, "before")))
        return stream_response(sse(end()))

    api, recorder, _ = make_api(handler)
    follow_stream(
        api, 7, DEPLOYMENT, tail=None, release=None, lookback=600, timestamps=False,
        out=io.StringIO(), say=lambda _m: None, sleep=lambda _s: None,
    )

    assert recorder.requests[0].url.params["lookback"] == "600"
    assert "lookback" not in recorder.requests[-1].url.params
    assert recorder.requests[-1].url.params["since"] == TS1


def test_the_platforms_refusal_of_a_window_is_reported_with_its_reason(make_api):
    api, _, _ = make_api(
        lambda request: json_response(
            400, {"detail": "A log can be read at most 14 days back; 30 days was requested."}
        )
    )
    with pytest.raises(FreepodError, match="at most 14 days back"):
        stream_once(
            api, 7, DEPLOYMENT, Cursor(), follow=False, lookback=30 * 86400,
            out=io.StringIO(), say=lambda _m: None,
        )


def test_an_empty_window_says_so(make_api, tmp_path):
    project_at(tmp_path)
    api, _, _ = make_api(
        lambda request: json_response(200, {"id": 7})
        if request.url.path == "/api/me"
        else stream_response(sse(end()))
    )
    said = []
    assert run(api, "prod", root=tmp_path, lookback=60, out=io.StringIO(), say=said.append) == 0
    assert any("in that window" in line for line in said)


# --------------------------------------------------------------------------
# --json
# --------------------------------------------------------------------------


def test_json_prints_one_object_per_line_with_a_string_timestamp(make_api, tmp_path):
    project_at(tmp_path)
    body = sse(log_event(TS1, "hello"), log_event(TS2, 'say "hi"', release=None), end())
    api, _, _ = make_api(
        lambda request: json_response(200, {"id": 7})
        if request.url.path == "/api/me"
        else stream_response(body)
    )
    out = io.StringIO()

    run(api, "prod", root=tmp_path, as_json=True, timestamps=True, out=out, say=lambda _m: None)

    lines = out.getvalue().splitlines()
    assert [json.loads(line) for line in lines] == [
        {"ts": TS1, "line": "hello", "release": RELEASE},
        {"ts": TS2, "line": 'say "hi"', "release": None},
    ]
    # Every digit of the timestamp, as a string: no float ever touched it.
    assert f'"ts":"{TS1}"' in lines[0]


# --------------------------------------------------------------------------
# --http
# --------------------------------------------------------------------------

REQUEST = {
    "ts": TS1,
    "time": "2026-10-23T12:50:48.123456789Z",
    "host": "myapp.freepod.eu",
    "remote_addr": "203.0.113.7",
    "method": "GET",
    "path": "/index.html",
    "protocol": "HTTP/2.0",
    "status": 200,
    "bytes": 512,
    "duration_ms": 32.412,
    "referer": "https://example.org/",
    "user_agent": "Mozilla/5.0 (X11; Linux x86_64)",
}


def request_event(record) -> str:
    return f"id: {record['ts']}\nevent: request\ndata: {json.dumps(record)}"


def test_a_request_prints_in_combined_log_format():
    assert format_request(REQUEST, timestamps=False) == (
        '203.0.113.7 - - [23/Oct/2026:12:50:48 +0000] "GET /index.html HTTP/2.0" 200 512 '
        '"https://example.org/" "Mozilla/5.0 (X11; Linux x86_64)"'
    )


def test_absent_headers_print_as_a_dash():
    line = format_request({**REQUEST, "referer": None, "user_agent": None}, timestamps=False)
    assert line.endswith('200 512 "-" "-"')


def test_quotes_and_control_characters_are_escaped_onto_one_line():
    line = format_request(
        {**REQUEST, "path": '/a"b\\c\nd', "user_agent": 'evil" agent'}, timestamps=False
    )
    assert "\n" not in line
    assert '"GET /a\\"b\\\\c\\x0ad HTTP/2.0"' in line
    assert line.endswith('"evil\\" agent"')
    # Splitting on unescaped quotes still yields exactly the combined fields.
    assert len(re.findall(r'"(?:[^"\\]|\\.)*"', line)) == 3


def test_timestamps_prefix_the_time_the_request_was_logged():
    line = format_request(REQUEST, timestamps=True)
    assert line.startswith(format_timestamp(TS1) + " 203.0.113.7 - - [")


def test_the_month_does_not_follow_the_locale(monkeypatch):
    import locale

    try:
        locale.setlocale(locale.LC_TIME, "de_DE.UTF-8")
    except locale.Error:
        pytest.skip("no German locale here")
    try:
        record = {**REQUEST, "time": "2026-03-05T01:02:03Z"}
        assert "[05/Mar/2026:01:02:03 +0000]" in format_request(record, timestamps=False)
    finally:
        locale.setlocale(locale.LC_TIME, "C")


def test_http_reads_the_access_log_endpoint(make_api, tmp_path):
    project_at(tmp_path)
    api, recorder, _ = make_api(
        lambda request: json_response(200, {"id": 7})
        if request.url.path == "/api/me"
        else stream_response(sse(request_event(REQUEST), end()))
    )
    out = io.StringIO()

    run(api, "prod", root=tmp_path, http=True, out=out, say=lambda _m: None)

    assert recorder.requests[-1].url.path == f"/api/users/7/deployments/{DEPLOYMENT}/http-log"
    assert out.getvalue() == format_request(REQUEST, timestamps=False) + "\n"


def test_http_json_prints_the_record_unchanged(make_api, tmp_path):
    project_at(tmp_path)
    api, _, _ = make_api(
        lambda request: json_response(200, {"id": 7})
        if request.url.path == "/api/me"
        else stream_response(sse(request_event(REQUEST), end()))
    )
    out = io.StringIO()

    run(api, "prod", root=tmp_path, http=True, as_json=True, out=out, say=lambda _m: None)

    assert json.loads(out.getvalue()) == REQUEST


def test_http_with_a_release_is_refused_before_anything_is_sent(stub_api, capsys):
    def handler(request):
        raise AssertionError(f"no request should be made, got {request.url}")

    stub_api(handler)
    assert main(["log", "--http", "-r", "3"]) == EXIT_USAGE
    assert "cannot be pinned to a release" in capsys.readouterr().err


def test_no_requests_is_reported_on_stderr(make_api, tmp_path):
    project_at(tmp_path)
    api, _, _ = make_api(
        lambda request: json_response(200, {"id": 7})
        if request.url.path == "/api/me"
        else stream_response(sse(end()))
    )
    out, said = io.StringIO(), []

    assert run(api, "prod", root=tmp_path, http=True, out=out, say=said.append) == 0
    assert out.getvalue() == ""
    assert any("No HTTP requests" in line for line in said)
