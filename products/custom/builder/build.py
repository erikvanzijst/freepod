#!/usr/bin/env python3
"""Entrypoint for one build: fetch, extract, plan, build, push, report.

Everything this container touches is tenant-controlled except its own code, so
each stage is written to fail closed:

  * the artifact is fetched with a presigned URL that expires and grants read
    on exactly one object — there is no credential here to steal;
  * the archive is extracted through Python's `tarfile` "data" filter with
    explicit size and entry bounds, because a sandbox is a containment
    boundary, not a reason to honor a traversal entry;
  * the result is reported through the pod's termination message, so nothing in
    this container ever needs write access to anything.

Any failure exits non-zero with the reason on stdout. The worker treats a
non-zero exit, or a success reporting no usable image, as a failed build.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path

# Pinned by digest and version-matched to the `railpack` binary in the
# Dockerfile (v0.36.4). The build plan is a contract between the two, so this
# is about that coupling rather than supply chain: a digest is
# content-addressed, and `ghcr.io/railwayapp/railpack-frontend:v0.36.4`
# resolves to exactly this.
FRONTEND_IMAGE = (
    "ghcr.io/railwayapp/railpack-frontend"
    "@sha256:282e3d0e542c9299c9fc4f938c9a5c45f0666d954264deaea59d13281121a91a"
)

# The name the frontend looks for inside `--local dockerfile=`.
PLAN_FILENAME = "railpack-plan.json"

# Where the Railpack images live upstream, and therefore the registry the
# internal one is configured to stand in for. Not a general mirror: this is the
# only host whose pulls are worth redirecting, since it is the only one a build
# reaches before running any of the tenant's own code.
UPSTREAM_REGISTRY = "ghcr.io"

# Repository prefix for the layer cache, under the same registry the built image
# is pushed to. One repository per owner per environment, never shared — see
# `cache_ref` for why both halves are needed: a build cache is an execution
# result keyed by a hash the tenant controls, so a cache reachable by two
# tenants is a channel between them, not an optimization.
#
# Same registry as the output on purpose. A cache hit's layers are then already
# where the push needs them, so BuildKit can mount them across repositories
# instead of pulling them down and sending them back up.
CACHE_REPO_PREFIX = "cache"

# A single moving tag: the cache is a rolling working set, not a history. Each
# export overwrites the last, and the blobs it stops referencing become
# unreferenced for the registry's own garbage collection to reclaim.
CACHE_TAG = "latest"

DIGEST_PREFIX = "sha256:"
DIGEST_HEX_LEN = 64


class BuildFailure(Exception):
    """A build that failed for a reason worth showing the user."""


def log(message: str) -> None:
    """Emit a progress line.

    Plain text, no control sequences: this output is stored verbatim and
    replayed to users through the build log endpoint.
    """
    print(f"==> {message}", flush=True)


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise BuildFailure(f"required environment variable {name} is not set")
    return value


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise BuildFailure(f"{name} must be an integer, got {raw!r}") from exc


class _BoundedReader:
    """A read-only view of `stream` that refuses to yield more than `limit`.

    This bounds the *compressed* input as it arrives, which is what lets the
    archive be extracted straight off the socket rather than staged on disk
    first. Exceptions raised here propagate out through `tarfile` untouched,
    so the failure keeps its own message rather than being reported as a
    corrupt archive.
    """

    def __init__(self, stream, limit: int) -> None:
        self._stream = stream
        self._limit = limit
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        try:
            chunk = self._stream.read(size)
        except (urllib.error.URLError, OSError) as exc:
            # The transfer died part-way. Distinguished from a malformed
            # archive so the user is told the download failed, not that their
            # tarball is broken.
            raise BuildFailure(f"could not retrieve the project archive: {exc}") from exc
        self.bytes_read += len(chunk)
        if self.bytes_read > self._limit:
            raise BuildFailure(f"project archive exceeds the {self._limit} byte limit")
        return chunk


@contextlib.contextmanager
def open_artifact(url: str, *, max_bytes: int):
    """Open the project archive for streaming, bounded at `max_bytes`.

    Nothing is staged on disk: the archive is extracted as it arrives, so the
    pod's ephemeral storage only ever holds the *extracted* tree rather than
    the tree plus a copy of the tarball it came from.

    `urlopen` raises before any body is read, so an expired credential or a
    reaped artifact is reported here with its status rather than surfacing
    later as an extraction error.
    """
    log(f"Streaming project archive (limit {max_bytes} bytes)")
    try:
        response = urllib.request.urlopen(url, timeout=120)  # noqa: S310 — presigned https
    except urllib.error.HTTPError as exc:
        # Most likely an expired credential or an artifact reaped by the
        # bucket's lifecycle rule; say which so the user can act on it.
        raise BuildFailure(
            f"could not retrieve the project archive: HTTP {exc.code} {exc.reason}"
        ) from exc
    except urllib.error.URLError as exc:
        raise BuildFailure(f"could not retrieve the project archive: {exc.reason}") from exc

    with response:
        yield _BoundedReader(response, max_bytes)


def extract_stream(fileobj, dest: Path, *, max_bytes: int, max_entries: int) -> None:
    """Unpack a tar stream into `dest`, rejecting anything that escapes it.

    `filter="data"` is Python's own answer to untrusted tarballs: it refuses
    absolute paths, `..` traversal, links pointing outside the destination,
    and device/special files. The size and entry bounds are applied *before*
    each member is written, so a decompression bomb is stopped rather than
    merely noticed — the member that would breach a limit is never extracted
    at all.

    Opened in `r|*` stream mode, which reads strictly forward and never seeks,
    so it works directly on a socket. That also means members must be handled
    in the order they arrive — which this loop does anyway.
    """
    log(f"Extracting archive (limit {max_bytes} bytes, {max_entries} entries)")
    dest.mkdir(parents=True, exist_ok=True)
    entries = 0
    total = 0
    try:
        with tarfile.open(fileobj=fileobj, mode="r|*") as tar:
            for member in tar:
                entries += 1
                if entries > max_entries:
                    raise BuildFailure(
                        f"project archive has more than {max_entries} entries"
                    )
                # The data filter *rewrites* an absolute path to a relative one
                # rather than refusing it, so this adds nothing to containment
                # — it is purely about telling the truth. Silently relocating
                # `/app/main.py` to `app/main.py` would surface much later as
                # an unexplained "no project detected", which is a worse
                # experience than saying the archive is malformed.
                if member.name.startswith("/"):
                    raise BuildFailure(
                        f"project archive contains an absolute path: {member.name}"
                    )
                if member.isreg():
                    total += member.size
                    if total > max_bytes:
                        raise BuildFailure(
                            f"project archive expands beyond the {max_bytes} byte limit"
                        )
                tar.extract(member, path=dest, filter="data")
    except tarfile.TarError as exc:
        # Covers both a corrupt archive and a member the data filter refused,
        # e.g. one resolving outside the extraction directory. A failure of the
        # transfer itself raises BuildFailure from the reader and passes
        # through here untouched, keeping the two causes distinguishable.
        if getattr(fileobj, "bytes_read", -1) == 0:
            raise BuildFailure("the project archive is empty") from exc
        raise BuildFailure(f"could not extract the project archive: {exc}") from exc

    log(f"Extracted {entries} entries, {total} bytes")


def _run(command: list[str], *, stage: str, env: dict[str, str] | None = None) -> None:
    """Run a subprocess, streaming its output into ours, and fail on non-zero.

    Output is inherited rather than captured so progress appears in the build
    log as it happens, which is the whole point of a log a user can poll.
    """
    log(f"{stage}: {' '.join(command)}")
    result = subprocess.run(command, check=False, env=env)
    if result.returncode != 0:
        raise BuildFailure(f"{stage} failed with exit status {result.returncode}")


def prepare_plan(source: Path, plan_dir: Path) -> None:
    """Detect the project's stack and emit a build plan.

    `--error-missing-start` turns "we could not work out how to run this" into
    a clear failure here, rather than an image that builds and then cannot be
    started by the chart.
    """
    plan_dir.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "railpack",
            "prepare",
            str(source),
            "--plan-out",
            str(plan_dir / PLAN_FILENAME),
            "--error-missing-start",
        ],
        stage="Detecting project stack",
    )
    if not (plan_dir / PLAN_FILENAME).is_file():
        raise BuildFailure("stack detection produced no build plan")


def buildkitd_config(registry: str) -> str:
    """The ephemeral daemon's registry configuration, as TOML.

    A mirror that does not have an image is not an error: BuildKit puts the
    upstream host last in the same list and falls through to it. So a railpack
    bump whose new base images have not been mirrored yet still builds, just at
    the old speed — which is why this may be configured before, or without, any
    mirroring having happened.
    """
    return (
        f'[registry."{UPSTREAM_REGISTRY}"]\n'
        f'  mirrors = ["{registry}"]\n'
        "\n"
        f'[registry."{registry}"]\n'
        "  insecure = true\n"
    )


def write_buildkitd_config(path: Path, registry: str) -> list[str]:
    """Write the daemon config and return the buildkitd flags that select it.

    Generated rather than baked into the image so `CAELUS_REGISTRY` stays the
    single place the registry is named; a checked-in TOML would be a second
    copy of that host, silently ignored whenever the two disagreed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(buildkitd_config(registry))
    return ["--config", str(path)]


def cache_ref(registry: str, scope: str, user_id: str) -> str:
    """The layer cache repository for one owner within one environment.

    Derived entirely from values the platform supplies — never from anything
    inside the archive — because this string *is* the isolation boundary. Two
    owners resolving to one ref would share a cache, and a shared build cache
    is a write primitive: poison an entry and the next tenant executes it.

    `scope` is why the owner alone is not enough. Dev and prod run separate
    databases behind one registry, so their user id sequences are independent:
    user 1 in dev and user 1 in prod are different people. Without the scope
    they would land on the same repository under the same moving tag and read
    each other's cache — the exact channel this is meant to prevent. The image
    repositories share that ambiguity today and get away with it only because
    their tags are unguessable build UUIDs, which a cache under one stable tag
    is not.
    """
    return f"{registry}/{CACHE_REPO_PREFIX}/{scope}/{user_id}:{CACHE_TAG}"


def buildkitd_env(extra_flags: list[str]) -> dict[str, str]:
    """This process's environment with `extra_flags` added to BUILDKITD_FLAGS.

    `buildctl-daemonless.sh` word-splits BUILDKITD_FLAGS into the daemon it
    spawns, so this is the only channel for a flag. Appended rather than
    assigned: the image already sets `--oci-worker-no-process-sandbox` there,
    without which rootless buildkitd does not start at all.
    """
    env = dict(os.environ)
    existing = env.get("BUILDKITD_FLAGS", "").split()
    env["BUILDKITD_FLAGS"] = " ".join(existing + extra_flags)
    return env


def build_and_push(
    *,
    source: Path,
    plan_dir: Path,
    metadata_file: Path,
    image_ref: str,
    cache_key: str,
    cache_image_ref: str,
    buildkitd_flags: list[str],
) -> None:
    """Run the gateway build and push the result to the registry.

    `railpack build` cannot push — it can only export a filesystem to a local
    directory — so the two-phase `prepare` + gateway form is the only route to
    a registry, and is what upstream documents for platforms.

    `buildctl-daemonless.sh` spawns an ephemeral rootless buildkitd for this one
    invocation and tears it down after, which is exactly the per-build daemon
    lifetime the isolation argument depends on. That daemon's state lives on an
    emptyDir and dies with the pod, so *every* local cache is cold on arrival —
    which is why the cache that survives has to be a remote one.
    """
    _run(
        [
            "buildctl-daemonless.sh",
            "build",
            "--frontend=gateway.v0",
            "--opt",
            f"source={FRONTEND_IMAGE}",
            "--opt",
            f"filename={PLAN_FILENAME}",
            # Namespaces the frontend's mount cache ids per owner. Now that a
            # per-owner remote cache exists, this is the second half of the
            # same boundary rather than a precaution about a hypothetical one.
            "--opt",
            f"build-arg:cache-key={cache_key}",
            "--local",
            f"context={source}",
            "--local",
            f"dockerfile={plan_dir}",
            # An absent ref is the normal first build for an owner. BuildKit
            # warns and carries on rather than failing, so there is nothing to
            # create up front and nothing to clean up when a repository is
            # emptied.
            "--import-cache",
            f"type=registry,ref={cache_image_ref},registry.insecure=true",
            # mode=max records the intermediate steps too, not just the layers
            # of the final image. The expensive step here is dependency
            # installation, whose result never reaches the runtime image — with
            # mode=min it would be re-run on every build and the cache would
            # buy almost nothing.
            #
            # ignore-error: the image has already been pushed by the time this
            # runs. A registry that is full, or briefly unreachable, must cost
            # the build its cache and nothing else — failing here would discard
            # a good image over a missed optimization.
            #
            # image-manifest with oci-mediatypes is what makes the cache
            # storable in a plain OCI registry at all; without it BuildKit
            # writes a manifest type registry.home rejects.
            "--export-cache",
            (
                f"type=registry,ref={cache_image_ref},mode=max,"
                "image-manifest=true,oci-mediatypes=true,"
                "ignore-error=true,registry.insecure=true"
            ),
            # registry.insecure: the internal registry presents a certificate
            # for a name it is not addressed by. Tracked separately; giving it
            # a cert-valid internal name would retire this.
            "--output",
            f"type=image,name={image_ref},push=true,registry.insecure=true",
            "--metadata-file",
            str(metadata_file),
            # Plain, not auto: auto would emit a redrawing TTY display, and
            # this output is stored and replayed rather than watched live.
            "--progress=plain",
        ],
        stage="Building and pushing image",
        env=buildkitd_env(buildkitd_flags),
    )


def read_digest(metadata_file: Path) -> str:
    """Pull the pushed manifest's digest out of buildctl's metadata file.

    This is the authoritative digest — deriving it any other way (parsing log
    output, re-resolving the tag) would either be forgeable by build output or
    racy against another push to the same tag.
    """
    try:
        metadata = json.loads(metadata_file.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildFailure(f"could not read build metadata: {exc}") from exc

    digest = metadata.get("containerimage.digest")
    if not isinstance(digest, str) or not digest.startswith(DIGEST_PREFIX):
        raise BuildFailure("build reported no image digest")

    hexpart = digest[len(DIGEST_PREFIX) :]
    if len(hexpart) != DIGEST_HEX_LEN or not all(c in "0123456789abcdef" for c in hexpart):
        raise BuildFailure(f"build reported a malformed image digest: {digest}")
    return digest


def write_termination_message(path: Path, payload: dict[str, str]) -> None:
    """Report the outcome through the pod's termination message.

    Purpose-built for this: a small structured result from a terminating
    container, surfaced through pod status, requiring no credential. Kubernetes
    caps it at 4 KiB, which is ample for one image reference.

    Failing to write it must not mask the build's own outcome, so a write error
    is reported and swallowed.
    """
    try:
        path.write_text(json.dumps(payload))
    except OSError as exc:
        print(f"warning: could not write termination message to {path}: {exc}", flush=True)


def main() -> int:
    termination_log = Path(os.environ.get("CAELUS_TERMINATION_LOG", "/dev/termination-log"))
    try:
        artifact_url = _env("CAELUS_ARTIFACT_URL")
        user_id = _env("CAELUS_USER_ID")
        build_id = _env("CAELUS_BUILD_ID")
        registry = _env("CAELUS_REGISTRY")
        # Required, not defaulted: a missing scope silently collapsing two
        # environments onto one cache repository is precisely the failure the
        # scope exists to prevent, so it fails the build instead.
        cache_scope = _env("CAELUS_CACHE_SCOPE")
        workdir = Path(os.environ.get("CAELUS_WORKDIR", "/home/user/work"))

        max_artifact_bytes = _env_int("CAELUS_ARTIFACT_MAX_BYTES", 100 * 1024 * 1024)
        max_extracted_bytes = _env_int("CAELUS_EXTRACTED_MAX_BYTES", 800 * 1024 * 1024)
        max_entries = _env_int("CAELUS_ARCHIVE_MAX_ENTRIES", 100_000)

        source = workdir / "src"
        plan_dir = workdir / "plan"
        metadata_file = workdir / "metadata.json"

        # A fresh tree per run, so a retried Job cannot inherit a partial one.
        shutil.rmtree(source, ignore_errors=True)

        # The tag is registry-side bookkeeping and is never exposed through the
        # API. It exists so the manifest is not left untagged: an untagged
        # manifest is removable by a registry garbage collection pass run with
        # --delete-untagged, which would silently break every deployment
        # referencing it by digest.
        image_ref = f"{registry}/{user_id}:{build_id}"

        # Scoped to the owner rather than to this build: a cache that only its
        # own build could read would never be read at all.
        cache_image_ref = cache_ref(registry, cache_scope, user_id)
        buildkitd_flags = write_buildkitd_config(workdir / "buildkitd.toml", registry)

        log(f"Build {build_id} for user {user_id}")
        with open_artifact(artifact_url, max_bytes=max_artifact_bytes) as stream:
            extract_stream(
                stream, source, max_bytes=max_extracted_bytes, max_entries=max_entries
            )
        prepare_plan(source, plan_dir)
        build_and_push(
            source=source,
            plan_dir=plan_dir,
            metadata_file=metadata_file,
            image_ref=image_ref,
            cache_key=user_id,
            cache_image_ref=cache_image_ref,
            buildkitd_flags=buildkitd_flags,
        )
        digest = read_digest(metadata_file)

        # The registry host is deliberately stripped: this exact string is what
        # the client submits as the product's `image` user value, and the chart
        # re-attaches the host. Withholding it is what stops a tenant pointing
        # a deployment at an arbitrary registry.
        image = f"{user_id}@{digest}"
        log(f"Built {image}")
        write_termination_message(termination_log, {"image": image})
        return 0

    except BuildFailure as exc:
        print(f"ERROR: {exc}", flush=True)
        # Deliberately carries no `image` key — the worker requires one to
        # treat a build as succeeded, so this can only ever read as a failure.
        write_termination_message(termination_log, {"error": str(exc)})
        return 1
    except Exception as exc:  # noqa: BLE001 — a crash here must still be a clean failure
        print(f"ERROR: unexpected build failure: {exc!r}", flush=True)
        write_termination_message(termination_log, {"error": f"unexpected failure: {exc!r}"})
        return 1


if __name__ == "__main__":
    sys.exit(main())
