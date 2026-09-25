"""Uploading the archive, creating the build, and streaming its log.

Three phases, in this order:

1. **Mint an upload slot** — `POST /api/artifacts`, *after* the archive is
   packed. A slot lives 900s, and 100 MiB over a domestic uplink can outlive
   that. Minting persists nothing, so an unused slot costs nothing.
2. **Submit the archive** — a presigned form POST straight to the object store,
   every field verbatim and in order with the file part last.
3. **Create and follow the build** — `POST
   /api/users/{uid}/deployments/{deployment_id}/builds` with the artifact id alone,
   then read the log by byte range until `X-Build-Status` is terminal. A build
   belongs to the project's deployment, so that deployment exists first.

See design D9, D12, and D13.
"""

from __future__ import annotations

import io
import sys
import time
from typing import Any, Callable, Dict, IO, NamedTuple, Optional, Tuple

import click
import httpx

from . import BuildFailed, FreepodError
from .api import ApiClient
from .archive import human
from .config import BUILD_WAIT_SECONDS, USER_AGENT

#: Statuses no further transition leaves. Mirrors the platform's own set; the
#: client stops at any of them rather than only at the one it hoped for.
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "canceled"})

STATUS_QUEUED = "queued"
STATUS_SUCCEEDED = "succeeded"

#: Poll cadence. The build worker's own loop is 1s, so polling faster buys
#: nothing; backing off while the log is idle keeps a long quiet build from
#: issuing a request per second for minutes.
POLL_ACTIVE_SECONDS = 1.0
POLL_IDLE_SECONDS = 3.0

#: How long the upload itself may take. Distinct from the per-request default,
#: which is sized for API calls rather than for 100 MiB over a domestic uplink.
UPLOAD_TIMEOUT_SECONDS = 900


def _log(message: str) -> None:
    print(message, file=sys.stderr)


class _ProgressReader:
    """Proxies a file object, reporting bytes as they are consumed.

    `seek` and `tell` are **required**, not conveniences. `httpx` uses `seek`
    to rewind the field before rendering it — which is what makes a retry send
    the archive again rather than nothing — and uses seek/tell to size the body
    so the request carries a `Content-Length` for the presigned policy's
    `content-length-range` condition to be evaluated against. Removing either
    turns a retry into a zero-byte upload.

    `fileno` is deliberately **not** exposed: a `SpooledTemporaryFile` that has
    not rolled over to disk has no descriptor, and letting the encoder discover
    one for a spilled archive but not an in-memory one would size the body by
    two different code paths depending on the project.
    """

    def __init__(self, handle: IO[bytes], on_read: Callable[[int], None]):
        self._handle = handle
        self._on_read = on_read

    def read(self, size: int = -1) -> bytes:
        chunk = self._handle.read(size)
        if chunk:
            self._on_read(len(chunk))
        return chunk

    def seek(self, offset: int, whence: int = 0) -> int:
        return self._handle.seek(offset, whence)

    def tell(self) -> int:
        return self._handle.tell()


# --------------------------------------------------------------------------
# Phase 1 and 2: slot and upload
# --------------------------------------------------------------------------


def mint_slot(api: ApiClient) -> Dict[str, Any]:
    """`POST /api/artifacts` — where to upload, and what to upload with."""
    response = api.post("/api/artifacts")
    if response.status_code != 201:
        raise FreepodError(
            f"could not obtain an upload slot: HTTP {response.status_code} "
            f"{response.text.strip()[:300]}"
        )
    slot = response.json()
    for key in ("artifact_id", "url", "fields", "max_bytes"):
        if key not in slot:
            raise FreepodError(f"upload slot is missing '{key}': {slot!r}")
    return slot


def check_size(size: int, slot: Dict[str, Any]) -> None:
    """Refuse an oversized archive before a byte is transferred.

    This is the **only** limit the client enforces, and it learns it at runtime
    from the slot rather than carrying its own copy. The archive's entry count
    and uncompressed ceiling live in the builder's environment and are never
    reported to a client; a client with hardcoded copies would drift the moment
    the platform retuned one, and drift toward refusing archives the platform
    would have accepted. See design D12.
    """
    limit = slot["max_bytes"]
    if size > limit:
        raise FreepodError(
            f"the packed archive is {human(size)} ({size} bytes), which exceeds this "
            f"platform's limit of {human(limit)} ({limit} bytes).\n"
            f"  Exclude what the build does not need — a .freepodignore works like "
            f".gitignore — and try again."
        )


def _submit(
    client: httpx.Client,
    slot: Dict[str, Any],
    handle: IO[bytes],
    size: int,
    *,
    quiet: bool = False,
) -> httpx.Response:
    """One presigned form POST of the whole archive.

    The explicit rewind is belt-and-braces, not the guard that matters.
    Measured: `httpx`'s multipart encoder rewinds a file field itself —
    `FileField.render_data` calls `self.file.seek(0)` when the object has a
    `seek` — so a resubmission from a fully consumed handle already sends the
    complete archive. What is actually load-bearing is that `_ProgressReader`
    **exposes `seek`**; drop it and httpx silently stops rewinding *and* can no
    longer size the body, which turns a retry into a zero-byte upload that the
    policy's lower bound of 1 then refuses — reported as "the fresh slot was
    rejected too", blaming the platform for a client bug.

    This line costs nothing and keeps the behavior correct if the transport
    ever changes, but the test that protects the invariant is the one asserting
    the reader is seekable.
    """
    handle.seek(0)

    # Progress is a diagnostic, so it goes to stderr — `click.progressbar`
    # would otherwise write to stdout and contaminate a piped result. Click
    # renders nothing when the stream is not a terminal, so a redirected run
    # needs no special case beyond choosing the right stream.
    destination = io.StringIO() if quiet else sys.stderr
    with click.progressbar(
        length=size,
        label=f"  uploading {human(size)}",
        file=destination,
    ) as bar:
        reader = _ProgressReader(handle, bar.update)
        # `fields` first and in order, file part last: the store validates the
        # signed policy, so reordering yields a rejection rather than a
        # differently-shaped upload.
        return client.post(
            slot["url"],
            data=dict(slot["fields"]),
            files={"file": ("archive.tar.gz", reader, "application/gzip")},
            timeout=UPLOAD_TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT},
        )


def upload_archive(
    api: ApiClient,
    handle: IO[bytes],
    size: int,
    *,
    client: Optional[httpx.Client] = None,
    quiet: bool = False,
    echo: Callable[[str], None] = _log,
) -> str:
    """Mint a slot, check the size, and submit. Returns the artifact id.

    The object store is a different host with a different credential model, so
    it is reached with a plain client rather than through `ApiClient` — no
    bearer token, and none of the 401/403 contract, which describes the
    platform's edge and not an S3-compatible store.
    """
    owned = client is None
    store = client if client is not None else httpx.Client()
    try:
        slot = mint_slot(api)
        check_size(size, slot)

        response = _submit(store, slot, handle, size, quiet=quiet)

        if response.status_code == 403:
            # An expired slot or a policy violation. Mint a fresh one and send
            # the same archive once more.
            echo("  upload slot rejected; obtaining a fresh one and retrying once.")
            slot = mint_slot(api)
            check_size(size, slot)
            response = _submit(store, slot, handle, size, quiet=quiet)

        if response.status_code not in (200, 201, 204):
            raise FreepodError(
                f"the object store refused the upload: HTTP {response.status_code} "
                f"{response.text.strip()[:500]}"
            )

        return slot["artifact_id"]
    finally:
        if owned:
            store.close()


# --------------------------------------------------------------------------
# Phase 3: build
# --------------------------------------------------------------------------


def builds_path(user_id: int, deployment_id: str) -> str:
    """Where a deployment's builds live: builds belong to a deployment."""
    return f"/api/users/{user_id}/deployments/{deployment_id}/builds"


def create_build(
    api: ApiClient, user_id: int, deployment_id: str, artifact_id: str
) -> Tuple[Dict[str, Any], bool]:
    """Create a build of the deployment, with the artifact id alone.

    Returns `(build, reattached)`. A **200** rather than 201 means the platform
    handed back a build already queued or running for this artifact instead of
    creating a second one — which is what makes re-running a deploy safe, and
    is worth saying out loud rather than silently following.
    """
    response = api.post(
        builds_path(user_id, deployment_id), json={"artifact_id": artifact_id}
    )
    if response.status_code not in (200, 201):
        detail = response.text.strip()[:300]
        raise FreepodError(f"could not create the build: HTTP {response.status_code} {detail}")
    return response.json(), response.status_code == 200


def follow_build(
    api: ApiClient,
    user_id: int,
    deployment_id: str,
    build_id: str,
    *,
    out: Optional[IO[bytes]] = None,
    timeout: int = BUILD_WAIT_SECONDS,
    poll_active: float = POLL_ACTIVE_SECONDS,
    poll_idle: float = POLL_IDLE_SECONDS,
    echo: Callable[[str], None] = _log,
) -> str:
    """Stream the log by byte range until the status is terminal.

    Returns the terminal status. Raises on interrupt after saying that the
    build continues without us.

    The log goes to **stderr**: it is the platform narrating its progress, not
    the result of the command. Putting it on stdout would mean `$(freepod
    deploy)` captured a few hundred lines of buildkit output with the address
    buried at the end.
    """
    stream = out if out is not None else sys.stderr.buffer
    offset = 0
    status = STATUS_QUEUED
    announced_queued = False
    deadline = time.monotonic() + timeout

    try:
        while True:
            response = api.get(
                f"{builds_path(user_id, deployment_id)}/{build_id}/log",
                headers={"Range": f"bytes={offset}-"},
            )
            if response.status_code not in (200, 206):
                raise FreepodError(
                    f"could not read the build log: HTTP {response.status_code} "
                    f"{response.text.strip()[:300]}"
                )

            # Present on every response, so nothing has to ask separately
            # whether the build is done.
            status = response.headers.get("X-Build-Status", status)
            chunk = response.content

            if chunk:
                stream.write(chunk)
                stream.flush()
                # Advance by bytes read, never by a decoded length: a chunk
                # boundary can fall inside a multi-byte character.
                offset += len(chunk)

            if status in TERMINAL_STATUSES:
                # The status travelled with the bytes, so stopping here needs
                # no further request.
                return status

            if status == STATUS_QUEUED and not announced_queued:
                echo("  Queued — waiting for a build worker...")
                announced_queued = True

            if time.monotonic() >= deadline:
                raise FreepodError(
                    f"stopped waiting after {timeout}s. The build is still running on "
                    f"the platform — it was not canceled (build {build_id})."
                )

            # An empty range starting at the current end is the steady state
            # while a build runs, not an error; it only means back off.
            time.sleep(poll_active if chunk else poll_idle)
    except KeyboardInterrupt:
        _log(
            f"\nInterrupted. The build continues on the platform and was not "
            f"canceled (build {build_id})."
        )
        raise


class Built(NamedTuple):
    """A successful build: what it produced, and which build produced it.

    Both halves travel together because the platform records provenance on the
    *release*, and an image reference cannot identify a build on its own — it
    is `{user_id}@{digest}`, and digests are content-addressed, so image ->
    build is many-to-one. Returning only the image, as this once did, meant
    every release recorded a null build and the chain from source archive to
    running pod was broken at its last link.
    """

    image: str
    build_id: str


def build_image(
    api: ApiClient,
    user_id: int,
    deployment_id: str,
    handle: IO[bytes],
    size: int,
    *,
    client: Optional[httpx.Client] = None,
    out: Optional[IO[bytes]] = None,
    timeout: int = BUILD_WAIT_SECONDS,
    quiet: bool = False,
    echo: Callable[[str], None] = _log,
) -> Built:
    """Upload, build for the deployment, and return the image reference with its build id.

    Raises `BuildFailed` — exit 4 — when the build reaches any terminal status
    other than success, so a caller cannot mistake a failed build for something
    releasable.
    """
    artifact_id = upload_archive(api, handle, size, client=client, quiet=quiet, echo=echo)

    build, reattached = create_build(api, user_id, deployment_id, artifact_id)
    build_id = build["id"]
    if reattached:
        echo(f"  Re-attaching to the build already in progress for this archive ({build_id}).")
    else:
        echo(f"  Build {build_id} queued.")

    status = follow_build(
        api, user_id, deployment_id, build_id, out=out, timeout=timeout, echo=echo
    )

    if status != STATUS_SUCCEEDED:
        raise BuildFailed(
            f"the build {status} (build {build_id}). Nothing has been deployed; "
            f"the log above is the platform's account of why."
        )

    # `image` is null until the build succeeds, so it is read from the record
    # afterwards rather than from the creation response.
    record = api.get_json(f"{builds_path(user_id, deployment_id)}/{build_id}")
    image = record.get("image")
    if not image:
        raise FreepodError(
            f"build {build_id} succeeded but carries no image reference — "
            f"this is an unexpected platform condition, please report it."
        )
    return Built(image=image, build_id=str(build_id))
