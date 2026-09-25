"""Upload, build creation, and log streaming (tasks 9.1 - 9.12)."""

from __future__ import annotations

import io
import re
import tempfile

import httpx
import pytest

from freepod import BuildFailed, FreepodError
from freepod.build import (
    TERMINAL_STATUSES,
    build_image,
    check_size,
    create_build,
    follow_build,
    mint_slot,
    upload_archive,
)

from conftest import json_response

SLOT_FIELDS = {
    "key": "artifacts/3f6c1e9a.tar.gz",
    "policy": "eyJleHBpcmF0aW9uIjoi",
    "x-amz-algorithm": "AWS4-HMAC-SHA256",
    "x-amz-credential": "cred/20260815/us-east-1/s3/aws4_request",
    "x-amz-date": "20260815T000000Z",
    "x-amz-signature": "deadbeef",
}


def slot(artifact_id="3f6c1e9a4b2d47c8a1e05d9f7b3c2a10", max_bytes=104857600):
    return {
        "artifact_id": artifact_id,
        "url": "https://blob.freepod.eu/caelus-artifacts",
        "fields": dict(SLOT_FIELDS),
        "max_bytes": max_bytes,
        "expires_in": 900,
    }


def archive(payload: bytes = b"ARCHIVE" * 500):
    handle = tempfile.SpooledTemporaryFile(max_size=1024)
    handle.write(payload)
    handle.seek(0)
    return handle, len(payload)


class Store:
    """A stand-in object store that records each submission."""

    def __init__(self, *statuses, body="Forbidden"):
        self.statuses = list(statuses) or [204]
        self.body = body
        self.submissions = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.submissions.append(request)
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        if status >= 400:
            return httpx.Response(status, content=self.body.encode())
        return httpx.Response(status)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))

    def part_names(self, index=0):
        body = self.submissions[index].content
        # The lookbehind matters: `filename="archive.tar.gz"` also contains
        # `name="`, and counting it would report a phantom extra part.
        return [match.decode() for match in re.findall(rb'(?<!file)name="([^"]+)"', body)]

    def payload_sizes(self):
        return [len(request.content) for request in self.submissions]


def platform(*, slots=None, build=None, build_status=201, log=None, record=None):
    """A scripted Freepod API. Records the order calls arrived in."""
    state = {"calls": [], "mints": 0}
    slot_queue = list(slots) if slots else None
    log_pages = list(log) if log else []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        state["calls"].append((request.method, path))

        if request.method == "POST" and path == "/api/artifacts":
            state["mints"] += 1
            body = slot_queue.pop(0) if slot_queue and len(slot_queue) > 1 else (
                slot_queue[0] if slot_queue else slot()
            )
            return json_response(201, body)

        if request.method == "POST" and path == "/api/users/7/deployments/d-1/builds":
            state["build_payload"] = request.content
            return json_response(build_status, build or {"id": "b-1", "status": "queued"})

        if path.endswith("/log"):
            state.setdefault("ranges", []).append(request.headers.get("range"))
            page = log_pages.pop(0) if len(log_pages) > 1 else (
                log_pages[0] if log_pages else (b"", "succeeded")
            )
            content, status = page
            return httpx.Response(
                206,
                content=content,
                headers={"X-Build-Status": status, "Accept-Ranges": "bytes"},
            )

        if path.startswith("/api/users/7/deployments/d-1/builds/"):
            return json_response(200, record or {"id": "b-1", "status": "succeeded",
                                                 "image": "5@sha256:" + "a" * 64})

        return json_response(404, {"detail": "Not Found"})

    return handler, state


# --------------------------------------------------------------------------
# The slot (tasks 9.1, 9.2, 9.3)
# --------------------------------------------------------------------------


def test_the_slot_is_minted_after_the_archive_is_packed(make_api):
    """A slot lives 900s; packing 100 MiB can outlive it."""
    handler, state = platform()
    api, _, _ = make_api(handler)
    store = Store(204)
    handle, size = archive()

    # `upload_archive` receives an already-packed handle, so packing has
    # necessarily happened before the first API call it makes.
    upload_archive(api, handle, size, client=store.client(), quiet=True)

    assert state["calls"][0] == ("POST", "/api/artifacts")


def test_an_oversized_archive_is_refused_before_any_byte_is_sent(make_api):
    handler, _ = platform(slots=[slot(max_bytes=1000)])
    api, _, _ = make_api(handler)
    store = Store(204)
    handle, size = archive(b"x" * 5000)

    with pytest.raises(FreepodError) as raised:
        upload_archive(api, handle, size, client=store.client(), quiet=True)

    message = str(raised.value)
    assert "5000 bytes" in message, "the packed size must be reported"
    assert "1000 bytes" in message, "the platform's limit must be reported"
    assert store.submissions == [], "nothing may be transferred before the check"


def test_the_size_limit_comes_from_the_slot_not_from_a_constant():
    """A raised platform limit takes effect without a client release."""
    check_size(5000, slot(max_bytes=10_000))
    with pytest.raises(FreepodError):
        check_size(5000, slot(max_bytes=4_999))


def test_no_other_platform_bound_is_hardcoded():
    """Design D12: entry count and uncompressed size are never client-side.

    A client carrying its own copy drifts the moment the platform retunes one,
    and drifts toward refusing archives the platform would have accepted, with
    a message no operator can override.
    """
    import pathlib

    import freepod

    source_root = pathlib.Path(freepod.__file__).parent
    forbidden = ("MAX_ENTRIES", "MAX_EXTRACTED", "max_entries", "max_extracted")
    offenders = []
    for path in source_root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for needle in forbidden:
            if needle in text:
                offenders.append(f"{path.name}: {needle}")

    assert offenders == []


def test_a_slot_missing_a_field_is_reported(make_api):
    def handler(request):
        return json_response(201, {"artifact_id": "a", "url": "u", "fields": {}})

    api, _, _ = make_api(handler)
    with pytest.raises(FreepodError, match="max_bytes"):
        mint_slot(api)


# --------------------------------------------------------------------------
# The submission (task 9.4)
# --------------------------------------------------------------------------


def test_every_field_is_sent_verbatim_and_in_order_with_the_file_last(make_api):
    handler, _ = platform()
    api, _, _ = make_api(handler)
    store = Store(204)
    handle, size = archive()

    upload_archive(api, handle, size, client=store.client(), quiet=True)

    names = store.part_names()
    assert names == list(SLOT_FIELDS) + ["file"]

    body = store.submissions[0].content
    for key, value in SLOT_FIELDS.items():
        assert value.encode() in body, f"{key} was altered or dropped"


def test_the_upload_carries_a_content_length(make_api):
    """The presigned policy's content-length-range is evaluated on the request."""
    handler, _ = platform()
    api, _, _ = make_api(handler)
    store = Store(204)
    handle, size = archive()

    upload_archive(api, handle, size, client=store.client(), quiet=True)

    request = store.submissions[0]
    assert request.headers.get("content-length") == str(len(request.content))


def test_the_archive_bytes_reach_the_store(make_api):
    handler, _ = platform()
    api, _, _ = make_api(handler)
    store = Store(204)
    payload = b"UNIQUE-ARCHIVE-CONTENT" * 20
    handle, size = archive(payload)

    upload_archive(api, handle, size, client=store.client(), quiet=True)

    assert payload in store.submissions[0].content


def test_the_upload_does_not_carry_a_bearer_token(make_api):
    """The store is a different host with a different credential model."""
    handler, _ = platform()
    api, _, _ = make_api(handler)
    store = Store(204)
    handle, size = archive()

    upload_archive(api, handle, size, client=store.client(), quiet=True)

    assert "authorization" not in store.submissions[0].headers


# --------------------------------------------------------------------------
# Re-minting (task 9.5)
# --------------------------------------------------------------------------


def test_an_expired_slot_is_re_minted_once_and_the_same_archive_resubmitted(make_api, capsys):
    handler, state = platform()
    api, _, _ = make_api(handler)
    store = Store(403, 204)
    handle, size = archive()

    artifact_id = upload_archive(api, handle, size, client=store.client(), quiet=True)

    assert state["mints"] == 2, "a fresh slot must be obtained, not the same one reused"
    assert len(store.submissions) == 2

    first, second = store.payload_sizes()
    assert first == second, (
        "the resubmit sent a different number of bytes — an unrewound handle "
        "sends zero and the store refuses it against the policy's lower bound"
    )
    assert second > size, "the body must still contain the archive plus its multipart framing"
    assert artifact_id
    capsys.readouterr()


def test_the_resubmitted_archive_is_byte_identical(make_api, capsys):
    handler, _ = platform()
    api, _, _ = make_api(handler)
    store = Store(403, 204)
    payload = b"REPLAY-ME" * 200
    handle, size = archive(payload)

    upload_archive(api, handle, size, client=store.client(), quiet=True)

    assert payload in store.submissions[1].content, "the retry lost the archive body"
    capsys.readouterr()


def test_a_fully_consumed_handle_still_uploads_the_whole_archive(make_api):
    """The behavior the retry depends on, asserted end to end.

    Measured, not assumed: `httpx` rewinds a file field itself, so this passes
    even with the client's own `seek(0)` removed. The test is here because it
    pins the *outcome* — a resubmit sends the archive, not nothing — which is
    what a reader cares about, and which survives changing how it is achieved.
    """
    handler, _ = platform()
    api, _, _ = make_api(handler)
    store = Store(204)
    payload = b"CONSUMED-THEN-SENT" * 50
    handle, size = archive(payload)
    handle.read()  # leave the handle at EOF, as a first attempt would

    upload_archive(api, handle, size, client=store.client(), quiet=True)

    assert payload in store.submissions[0].content
    assert store.submissions[0].headers.get("content-length") == str(
        len(store.submissions[0].content)
    )


def test_the_progress_reader_is_seekable():
    """The actual guard behind the retry, and behind Content-Length.

    `httpx` rewinds a file field only when it has `seek`, and sizes the body by
    seek/tell. A reader without them yields a chunked, unrewound upload — zero
    bytes on a retry, and no `Content-Length` for the presigned policy's
    `content-length-range` condition to be checked against.
    """
    from freepod.build import _ProgressReader

    reader = _ProgressReader(io.BytesIO(b"0123456789"), lambda _n: None)

    assert hasattr(reader, "seek") and hasattr(reader, "tell")
    assert reader.seek(0, 2) == 10 and reader.tell() == 10
    assert reader.seek(0) == 0
    assert reader.read() == b"0123456789"
    # No `fileno`: a spooled archive has one only after rolling over to disk,
    # and the encoder must not size in-memory and spilled archives differently.
    assert not hasattr(reader, "fileno")


def test_a_repeatedly_refused_upload_reports_the_stores_response(make_api, capsys):
    handler, _ = platform()
    api, _, _ = make_api(handler)
    store = Store(403, 403, body="EntityTooLarge: policy violation")
    handle, size = archive()

    with pytest.raises(FreepodError) as raised:
        upload_archive(api, handle, size, client=store.client(), quiet=True)

    assert "EntityTooLarge" in str(raised.value)
    assert len(store.submissions) == 2, "exactly one retry, then stop"
    capsys.readouterr()


def test_a_non_403_store_failure_is_not_retried(make_api):
    handler, _ = platform()
    api, _, _ = make_api(handler)
    store = Store(500, body="Internal Error")
    handle, size = archive()

    with pytest.raises(FreepodError, match="Internal Error"):
        upload_archive(api, handle, size, client=store.client(), quiet=True)

    assert len(store.submissions) == 1


# --------------------------------------------------------------------------
# Build creation (task 9.6)
# --------------------------------------------------------------------------


def test_the_build_is_created_with_the_artifact_id_alone(make_api):
    import json

    handler, state = platform()
    api, _, _ = make_api(handler)

    create_build(api, 7, "d-1", "3f6c1e9a4b2d47c8a1e05d9f7b3c2a10")

    payload = json.loads(state["build_payload"])
    assert payload == {"artifact_id": "3f6c1e9a4b2d47c8a1e05d9f7b3c2a10"}, (
        "the owner comes from the session; any other field is rejected outright"
    )


def test_a_201_is_a_new_build(make_api):
    handler, _ = platform(build_status=201, build={"id": "b-9", "status": "queued"})
    api, _, _ = make_api(handler)

    build, reattached = create_build(api, 7, "d-1", "a" * 32)

    assert build["id"] == "b-9"
    assert reattached is False


def test_a_200_is_reported_as_re_attaching(make_api, capsys):
    handler, _ = platform(
        build_status=200,
        build={"id": "b-running", "status": "running"},
        log=[(b"already going\n", "succeeded")],
    )
    api, _, _ = make_api(handler)
    store = Store(204)
    handle, size = archive()

    build_image(api, 7, "d-1", handle, size, client=store.client(), out=io.BytesIO(), quiet=True)

    stderr = capsys.readouterr().err
    assert "Re-attaching" in stderr
    assert "b-running" in stderr


def test_a_200_does_not_create_a_second_build(make_api):
    handler, state = platform(build_status=200, build={"id": "b-1", "status": "running"})
    api, _, _ = make_api(handler)

    create_build(api, 7, "d-1", "a" * 32)

    assert [call for call in state["calls"] if call == ("POST", "/api/users/7/deployments/d-1/builds")] == [
        ("POST", "/api/users/7/deployments/d-1/builds")
    ]


# --------------------------------------------------------------------------
# Log streaming (tasks 9.7, 9.8, 9.9)
# --------------------------------------------------------------------------


def test_output_is_streamed_as_it_arrives(make_api):
    handler, _ = platform(
        log=[(b"step 1\n", "running"), (b"step 2\n", "running"), (b"done\n", "succeeded")]
    )
    api, _, _ = make_api(handler)
    out = io.BytesIO()

    status = follow_build(api, 7, "d-1", "b-1", out=out, poll_active=0, poll_idle=0)

    assert status == "succeeded"
    assert out.getvalue() == b"step 1\nstep 2\ndone\n"


def test_no_byte_is_displayed_twice(make_api):
    pages = [(b"aaa", "running"), (b"bbb", "running"), (b"ccc", "running"), (b"", "succeeded")]
    handler, state = platform(log=pages)
    api, _, _ = make_api(handler)
    out = io.BytesIO()

    follow_build(api, 7, "d-1", "b-1", out=out, poll_active=0, poll_idle=0)

    assert out.getvalue() == b"aaabbbccc"
    # The offset advances by bytes read, so each request asks for what follows.
    assert state["ranges"] == ["bytes=0-", "bytes=3-", "bytes=6-", "bytes=9-"]


def test_the_offset_advances_by_bytes_not_characters(make_api):
    """A chunk boundary can fall inside a multi-byte character."""
    chunk = "héllo wörld".encode("utf-8")  # 13 bytes, 11 characters
    handler, state = platform(log=[(chunk, "running"), (b"", "succeeded")])
    api, _, _ = make_api(handler)

    follow_build(api, 7, "d-1", "b-1", out=io.BytesIO(), poll_active=0, poll_idle=0)

    assert state["ranges"][1] == f"bytes={len(chunk)}-"
    assert len(chunk) == 13


def test_an_empty_range_is_not_an_error(make_api):
    handler, _ = platform(
        log=[(b"", "running"), (b"", "running"), (b"output\n", "succeeded")]
    )
    api, _, _ = make_api(handler)
    out = io.BytesIO()

    status = follow_build(api, 7, "d-1", "b-1", out=out, poll_active=0, poll_idle=0)

    assert status == "succeeded"
    assert out.getvalue() == b"output\n"


@pytest.mark.parametrize("terminal", sorted(TERMINAL_STATUSES))
def test_streaming_stops_at_every_terminal_status(terminal, make_api):
    handler, state = platform(log=[(b"work\n", "running"), (b"last\n", terminal)])
    api, _, _ = make_api(handler)

    status = follow_build(api, 7, "d-1", "b-1", out=io.BytesIO(), poll_active=0, poll_idle=0)

    assert status == terminal
    # Two log reads and nothing else: the status travelled with the bytes.
    assert state["calls"] == [
        ("GET", "/api/users/7/deployments/d-1/builds/b-1/log"),
        ("GET", "/api/users/7/deployments/d-1/builds/b-1/log"),
    ]


def test_the_final_chunk_is_written_before_stopping(make_api):
    handler, _ = platform(log=[(b"the last words\n", "failed")])
    api, _, _ = make_api(handler)
    out = io.BytesIO()

    follow_build(api, 7, "d-1", "b-1", out=out, poll_active=0, poll_idle=0)

    assert out.getvalue() == b"the last words\n"


def test_a_queued_build_says_it_is_waiting(make_api, capsys):
    handler, _ = platform(
        log=[(b"", "queued"), (b"", "queued"), (b"go\n", "succeeded")]
    )
    api, _, _ = make_api(handler)

    follow_build(api, 7, "d-1", "b-1", out=io.BytesIO(), poll_active=0, poll_idle=0)

    stderr = capsys.readouterr().err
    assert "Queued" in stderr
    assert stderr.count("Queued") == 1, "the notice must not repeat on every poll"


def test_polling_backs_off_while_no_output_arrives(make_api, monkeypatch):
    handler, _ = platform(
        log=[(b"busy\n", "running"), (b"", "running"), (b"", "succeeded")]
    )
    api, _, _ = make_api(handler)

    slept = []
    monkeypatch.setattr("freepod.build.time.sleep", lambda seconds: slept.append(seconds))

    follow_build(api, 7, "d-1", "b-1", out=io.BytesIO(), poll_active=1.0, poll_idle=3.0)

    assert slept == [1.0, 3.0], "1s while output arrives, 3s while idle"


def test_a_wait_that_times_out_says_the_build_continues(make_api):
    handler, _ = platform(log=[(b"slow\n", "running")])
    api, _, _ = make_api(handler)

    with pytest.raises(FreepodError) as raised:
        follow_build(api, 7, "d-1", "b-42", out=io.BytesIO(), timeout=0, poll_active=0, poll_idle=0)

    message = str(raised.value)
    assert "stopped waiting" in message
    assert "not canceled" in message
    assert "b-42" in message


# --------------------------------------------------------------------------
# Interruption (task 9.10)
# --------------------------------------------------------------------------


def test_an_interrupt_says_the_build_continues_and_names_it(make_api, capsys):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] > 1:
            raise KeyboardInterrupt
        return httpx.Response(206, content=b"working\n", headers={"X-Build-Status": "running"})

    api, _, _ = make_api(handler)

    with pytest.raises(KeyboardInterrupt):
        follow_build(api, 7, "d-1", "b-abc123", out=io.BytesIO(), poll_active=0, poll_idle=0)

    stderr = capsys.readouterr().err
    assert "continues on the platform" in stderr
    assert "not canceled" in stderr
    assert "b-abc123" in stderr


# --------------------------------------------------------------------------
# Outcome (task 9.11)
# --------------------------------------------------------------------------


def test_a_failed_build_stops_before_release(make_api, capsys):
    handler, state = platform(log=[(b"compile error\n", "failed")])
    api, _, _ = make_api(handler)
    store = Store(204)
    handle, size = archive()

    with pytest.raises(BuildFailed) as raised:
        build_image(api, 7, "d-1", handle, size, client=store.client(), out=io.BytesIO(), quiet=True)

    assert "failed" in str(raised.value)
    assert "Nothing has been deployed" in str(raised.value)
    # Nothing was done to the deployment itself; only its builds were touched.
    assert not any(
        re.fullmatch(r"/api/users/\d+/deployments(/[^/]+)?", path)
        for _method, path in state["calls"]
    )
    capsys.readouterr()


def test_a_failed_build_exits_four(make_api, capsys):
    from freepod import EXIT_BUILD_FAILED

    handler, _ = platform(log=[(b"", "failed")])
    api, _, _ = make_api(handler)
    store = Store(204)
    handle, size = archive()

    with pytest.raises(BuildFailed) as raised:
        build_image(api, 7, "d-1", handle, size, client=store.client(), out=io.BytesIO(), quiet=True)

    assert raised.value.exit_code == EXIT_BUILD_FAILED
    capsys.readouterr()


def test_a_canceled_build_also_stops(make_api, capsys):
    handler, _ = platform(log=[(b"", "canceled")])
    api, _, _ = make_api(handler)
    store = Store(204)
    handle, size = archive()

    with pytest.raises(BuildFailed, match="canceled"):
        build_image(api, 7, "d-1", handle, size, client=store.client(), out=io.BytesIO(), quiet=True)
    capsys.readouterr()


def test_a_successful_build_yields_the_image_reference(make_api, capsys):
    digest = "5@sha256:" + "a" * 64
    handler, state = platform(
        log=[(b"built\n", "succeeded")],
        record={"id": "b-1", "status": "succeeded", "image": digest},
    )
    api, _, _ = make_api(handler)
    store = Store(204)
    handle, size = archive()

    built = build_image(api, 7, "d-1", handle, size, client=store.client(), out=io.BytesIO(), quiet=True)

    assert built.image == digest
    # The build id travels with the image, because the platform records
    # provenance on the release and an image reference cannot identify a build
    # on its own -- digests are content-addressed, so image -> build is
    # many-to-one.
    assert built.build_id == "b-1"
    # `image` is null until success, so it is read from the record afterwards.
    assert ("GET", "/api/users/7/deployments/d-1/builds/b-1") in state["calls"]
    capsys.readouterr()


def test_a_success_without_an_image_is_a_platform_condition(make_api, capsys):
    handler, _ = platform(
        log=[(b"", "succeeded")], record={"id": "b-1", "status": "succeeded", "image": None}
    )
    api, _, _ = make_api(handler)
    store = Store(204)
    handle, size = archive()

    with pytest.raises(FreepodError, match="unexpected platform condition"):
        build_image(api, 7, "d-1", handle, size, client=store.client(), out=io.BytesIO(), quiet=True)
    capsys.readouterr()


# --------------------------------------------------------------------------
# Ordering of the whole phase
# --------------------------------------------------------------------------


def test_the_phases_happen_in_order(make_api, capsys):
    handler, state = platform(log=[(b"ok\n", "succeeded")])
    api, _, _ = make_api(handler)
    store = Store(204)
    handle, size = archive()

    build_image(api, 7, "d-1", handle, size, client=store.client(), out=io.BytesIO(), quiet=True)

    assert state["calls"] == [
        ("POST", "/api/artifacts"),
        ("POST", "/api/users/7/deployments/d-1/builds"),
        ("GET", "/api/users/7/deployments/d-1/builds/b-1/log"),
        ("GET", "/api/users/7/deployments/d-1/builds/b-1"),
    ]
    capsys.readouterr()


def test_the_build_log_goes_to_stdout_and_progress_to_stderr(make_api, capsys):
    """Build output is a result; progress and status are diagnostics."""
    handler, _ = platform(log=[(b"BUILD-OUTPUT\n", "succeeded")])
    api, _, _ = make_api(handler)
    store = Store(204)
    handle, size = archive()

    out = io.BytesIO()
    build_image(api, 7, "d-1", handle, size, client=store.client(), out=out, quiet=True)

    captured = capsys.readouterr()
    assert out.getvalue() == b"BUILD-OUTPUT\n"
    assert "BUILD-OUTPUT" not in captured.err
    assert "queued" in captured.err.lower() or "Build" in captured.err
