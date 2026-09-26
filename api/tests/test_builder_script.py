"""The builder container's entrypoint: archive handling and result reporting.

`products/custom/builder/build.py` is the one place in this codebase that
parses attacker-controlled input — a tenant's project archive — so its
extraction path is tested here rather than only exercised by a real build.
Everything in this file runs offline: no cluster, no registry, no object store.

The script lives outside `api/`, but `cd api && pytest` is the repo's only test
command, so this deliberately reaches across into `products/` (the same
intentional coupling as `test_tos_version_source.py`). A test that the standard
command does not run is a test that does not exist.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import tarfile
import time
import tomllib
import urllib.error
from datetime import UTC, datetime
from pathlib import Path

import pytest

# api/tests/ -> api/ -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = REPO_ROOT / "products" / "custom" / "builder" / "build.py"


def _load_build_module():
    assert BUILD_SCRIPT.is_file(), f"builder entrypoint not found at {BUILD_SCRIPT}"
    spec = importlib.util.spec_from_file_location("builder_build", BUILD_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = _load_build_module()


@pytest.fixture(autouse=True)
def _no_host_cgroup(monkeypatch, tmp_path):
    """Keep `main` off the test machine's own cgroup: it reports no usage unless
    a test hands it one."""
    monkeypatch.setattr(build, "CGROUP_ROOT", tmp_path / "no-cgroup")


# ---------------------------------------------------------------------------
# Archive construction helpers
# ---------------------------------------------------------------------------


def _regular(name: str, size: int = 0) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = tarfile.REGTYPE
    info.size = size
    return info


def _link(name: str, target: str, *, symbolic: bool = True) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = tarfile.SYMTYPE if symbolic else tarfile.LNKTYPE
    info.linkname = target
    return info


def _tarball(entries: list[tuple[tarfile.TarInfo, bytes | None]]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for info, payload in entries:
            tar.addfile(info, io.BytesIO(payload) if payload is not None else None)
    return buffer.getvalue()


class _Source:
    """A non-seekable byte source, like an HTTP response.

    `die_after` simulates a transfer that drops part-way through, which is the
    failure the streaming design has to keep distinguishable from a malformed
    archive.
    """

    def __init__(self, data: bytes, *, die_after: int | None = None) -> None:
        self._raw = io.BytesIO(data)
        self._die_after = die_after
        self._served = 0

    def read(self, size: int = -1) -> bytes:
        if self._die_after is not None and self._served >= self._die_after:
            raise OSError("connection reset by peer")
        chunk = self._raw.read(size)
        self._served += len(chunk)
        return chunk


def _extract(
    data: bytes,
    dest: Path,
    *,
    max_bytes: int = 1024 * 1024,
    max_entries: int = 1000,
    stream_limit: int = 10**9,
    die_after: int | None = None,
) -> None:
    """Extract through the same bounded-stream path production uses."""
    reader = build._BoundedReader(_Source(data, die_after=die_after), stream_limit)
    build.extract_stream(reader, dest, max_bytes=max_bytes, max_entries=max_entries)


# ---------------------------------------------------------------------------
# Hostile archives
#
# A sandbox is a containment boundary, not a reason to honor a traversal entry.
# Each case asserts both that extraction failed *and* that nothing was written
# outside the destination — the second is the property that actually matters.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label,entries",
    [
        ("parent traversal", [(_regular("../escape.txt", 5), b"pwned")]),
        ("deep traversal", [(_regular("../../escape.txt", 5), b"pwned")]),
        ("traversal below a directory", [(_regular("app/../../escape.txt", 5), b"pwned")]),
        ("absolute path", [(_regular("/tmp/escape.txt", 5), b"pwned")]),
        ("symlink to an absolute path", [(_link("evil", "/etc/passwd"), None)]),
        ("symlink escaping via ..", [(_link("evil", "../../outside"), None)]),
        ("hardlink to an absolute path", [(_link("evil", "/etc/passwd", symbolic=False), None)]),
    ],
)
def test_escaping_entries_are_rejected_and_write_nothing_outside(tmp_path, label, entries):
    dest = tmp_path / "src"
    sentinel = tmp_path / "escape.txt"

    with pytest.raises(build.BuildFailure):
        _extract(_tarball(entries), dest)

    assert not sentinel.exists(), f"{label}: wrote outside the extraction directory"
    strays = [p for p in tmp_path.rglob("*") if p.is_file() and dest not in p.parents]
    assert strays == [], f"{label}: stray files {strays}"


def test_entry_count_bomb_is_rejected(tmp_path):
    entries = [(_regular(f"f{n}", 0), b"") for n in range(50)]

    with pytest.raises(build.BuildFailure, match="more than 10 entries"):
        _extract(_tarball(entries), tmp_path / "src", max_entries=10)


def test_a_single_oversized_member_is_rejected(tmp_path):
    entries = [(_regular("big", 500_000), b"\0" * 500_000)]

    with pytest.raises(build.BuildFailure, match="expands beyond"):
        _extract(_tarball(entries), tmp_path / "src", max_bytes=1024)


def test_expansion_spread_across_many_members_is_rejected(tmp_path):
    """The bound is cumulative; no single member need breach it."""
    entries = [(_regular(f"f{n}", 100_000), b"\0" * 100_000) for n in range(20)]

    with pytest.raises(build.BuildFailure, match="expands beyond"):
        _extract(_tarball(entries), tmp_path / "src", max_bytes=500_000)


def test_the_breaching_member_is_never_written(tmp_path):
    """Bounds are checked *before* each member, so the cap is not merely noticed."""
    dest = tmp_path / "src"
    entries = [
        (_regular("small.txt", 10), b"0123456789"),
        (_regular("huge.bin", 100_000), b"\0" * 100_000),
    ]

    with pytest.raises(build.BuildFailure, match="expands beyond"):
        _extract(_tarball(entries), dest, max_bytes=1000)

    assert (dest / "small.txt").is_file()
    assert not (dest / "huge.bin").exists()


def test_a_compressed_stream_far_smaller_than_its_expansion_is_still_bounded(tmp_path):
    """The compressed cap alone would not have caught this.

    Highly compressible input reaches enormous ratios, which is exactly why the
    extracted-size bound exists separately from the download bound.
    """
    entries = [(_regular(f"f{n}", 100_000), b"\0" * 100_000) for n in range(5)]
    data = _tarball(entries)
    assert len(data) < 5_000, "test archive should be tiny compared to its expansion"

    with pytest.raises(build.BuildFailure, match="expands beyond"):
        _extract(data, tmp_path / "src", max_bytes=100_000, stream_limit=10**9)


# ---------------------------------------------------------------------------
# Benign archives still work
# ---------------------------------------------------------------------------


def test_a_normal_source_tree_extracts(tmp_path):
    dest = tmp_path / "src"
    entries = [
        (_regular("app/index.js", 11), b"console.log"),
        (_regular("app/package.json", 2), b"{}"),
    ]

    _extract(_tarball(entries), dest)

    assert (dest / "app" / "index.js").read_bytes() == b"console.log"
    assert (dest / "app" / "package.json").read_bytes() == b"{}"


def test_a_relative_link_inside_the_tree_is_preserved(tmp_path):
    """The filter refuses links that *escape*, not links as such."""
    dest = tmp_path / "src"
    entries = [(_regular("app/real.txt", 2), b"hi"), (_link("app/alias.txt", "real.txt"), None)]

    _extract(_tarball(entries), dest)

    assert (dest / "app" / "alias.txt").is_symlink()


# ---------------------------------------------------------------------------
# Streaming: bounds and error attribution
#
# Extraction runs straight off the socket, so a transfer failure surfaces from
# inside tarfile. These pin that each cause keeps its own message — a user told
# "your archive is corrupt" when the download died would go looking in the
# wrong place.
# ---------------------------------------------------------------------------


def test_the_compressed_stream_is_bounded_independently(tmp_path):
    data = _tarball([(_regular("app/f", 10), b"0123456789")])

    with pytest.raises(build.BuildFailure, match="exceeds the 10 byte limit"):
        _extract(data, tmp_path / "src", stream_limit=10)


def _incompressible_tarball(members: int = 5, size: int = 20_000) -> bytes:
    """An archive large enough to span several reads of the stream.

    Random payload on purpose: a compressible one would arrive in a single
    read, and a transfer cannot die part-way through if there is only one part.
    """
    import os

    return _tarball([(_regular(f"f{n}", size), os.urandom(size)) for n in range(members)])


def test_a_dead_transfer_reads_as_a_retrieval_failure(tmp_path):
    data = _incompressible_tarball()
    assert len(data) > 32_768, "archive must be large enough to require several reads"

    with pytest.raises(build.BuildFailure, match="could not retrieve") as exc:
        _extract(data, tmp_path / "src", max_bytes=10**7, die_after=16_384)

    assert "could not extract" not in str(exc.value)


def test_a_truncated_archive_reads_as_an_extraction_failure(tmp_path):
    data = _incompressible_tarball()

    with pytest.raises(build.BuildFailure, match="could not extract") as exc:
        _extract(data[: len(data) // 2], tmp_path / "src", max_bytes=10**7)

    assert "could not retrieve" not in str(exc.value)


def test_an_empty_body_is_named_as_such(tmp_path):
    with pytest.raises(build.BuildFailure, match="empty"):
        _extract(b"", tmp_path / "src")


def test_bounded_reader_reports_what_it_has_served():
    payload = b"x" * 100
    reader = build._BoundedReader(_Source(payload), 10**9)

    assert reader.read(40) == payload[:40]
    assert reader.bytes_read == 40


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------


def test_an_http_error_names_the_status(monkeypatch):
    """An expired credential or a lifecycle-reaped artifact must say so."""

    def _raise(*args, **kwargs):
        raise urllib.error.HTTPError("http://x", 403, "Forbidden", {}, None)

    monkeypatch.setattr(build.urllib.request, "urlopen", _raise)

    with pytest.raises(build.BuildFailure, match="HTTP 403"):
        with build.open_artifact("http://x", max_bytes=1024):
            pass


def test_an_unreachable_host_is_reported_as_a_retrieval_failure(monkeypatch):
    def _raise(*args, **kwargs):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(build.urllib.request, "urlopen", _raise)

    with pytest.raises(build.BuildFailure, match="could not retrieve"):
        with build.open_artifact("http://x", max_bytes=1024):
            pass


# ---------------------------------------------------------------------------
# Reading the produced digest
# ---------------------------------------------------------------------------


def test_digest_is_read_from_the_metadata_file(tmp_path):
    digest = "sha256:" + "a" * 64
    path = tmp_path / "metadata.json"
    path.write_text(json.dumps({"containerimage.digest": digest}))

    assert build.read_digest(path) == digest


@pytest.mark.parametrize(
    "metadata",
    [
        {},
        {"containerimage.digest": ""},
        {"containerimage.digest": None},
        {"containerimage.digest": 12345},
        {"containerimage.digest": "notadigest"},
        {"containerimage.digest": "sha256:" + "a" * 63},
        {"containerimage.digest": "sha256:" + "a" * 65},
        {"containerimage.digest": "sha256:" + "A" * 64},
        {"containerimage.digest": "sha256:" + "z" * 64},
    ],
)
def test_a_missing_or_malformed_digest_fails_the_build(tmp_path, metadata):
    """A success reporting no usable image is a failed build, not a success."""
    path = tmp_path / "metadata.json"
    path.write_text(json.dumps(metadata))

    with pytest.raises(build.BuildFailure):
        build.read_digest(path)


def test_unreadable_metadata_fails_the_build(tmp_path):
    with pytest.raises(build.BuildFailure, match="could not read build metadata"):
        build.read_digest(tmp_path / "does-not-exist.json")


def test_unparseable_metadata_fails_the_build(tmp_path):
    path = tmp_path / "metadata.json"
    path.write_text("{not json")

    with pytest.raises(build.BuildFailure, match="could not read build metadata"):
        build.read_digest(path)


# ---------------------------------------------------------------------------
# Reporting the result
# ---------------------------------------------------------------------------


def test_success_payload_carries_the_flat_image_reference(tmp_path):
    path = tmp_path / "term"

    build.write_termination_message(path, {"image": "5@sha256:" + "b" * 64})

    assert json.loads(path.read_text()) == {"image": "5@sha256:" + "b" * 64}


def test_failure_payload_carries_no_image_key(tmp_path):
    """The worker requires `image` to call a build succeeded, so a failure
    report can never be mistaken for one."""
    path = tmp_path / "term"

    build.write_termination_message(path, {"error": "stack detection failed"})

    assert "image" not in json.loads(path.read_text())


def test_an_unwritable_termination_path_does_not_mask_the_outcome(tmp_path):
    """Failing to report must not turn a finished build into a crash."""
    build.write_termination_message(tmp_path / "no-such-dir" / "term", {"image": "x"})


# ---------------------------------------------------------------------------
# Measuring usage
# ---------------------------------------------------------------------------


def _cgroup(
    root: Path,
    *,
    usage_usec: int = 41_200_000,
    current: int = 900_000_000,
    inactive_file: int = 100_000_000,
    peak: int = 812_000_000,
) -> Path:
    """A cgroup v2 directory shaped like the kernel's, with only what is read."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "cpu.stat").write_text(
        f"usage_usec {usage_usec}\nuser_usec 30000000\nsystem_usec 11200000\n"
        "nr_periods 0\nnr_throttled 0\nthrottled_usec 0\n"
    )
    (root / "memory.current").write_text(f"{current}\n")
    (root / "memory.stat").write_text(
        f"anon 700000000\nfile 200000000\nactive_file 100000000\n"
        f"inactive_file {inactive_file}\nslab 1000\n"
    )
    (root / "memory.peak").write_text(f"{peak}\n")
    return root


def test_cpu_is_read_from_cpu_stat_in_seconds(tmp_path):
    assert build.read_cpu_seconds(_cgroup(tmp_path, usage_usec=41_200_000)) == 41.2


def test_working_set_excludes_inactive_file_cache(tmp_path):
    root = _cgroup(tmp_path, current=900_000_000, inactive_file=100_000_000)

    assert build.read_working_set(root) == 800_000_000


def test_working_set_never_goes_negative(tmp_path):
    root = _cgroup(tmp_path, current=100, inactive_file=200)

    assert build.read_working_set(root) == 0


def test_peak_memory_is_read_from_memory_peak(tmp_path):
    assert build.read_memory_peak(_cgroup(tmp_path, peak=812_000_000)) == 812_000_000


def test_a_stat_file_missing_its_key_is_an_error(tmp_path):
    root = _cgroup(tmp_path)
    (root / "cpu.stat").write_text("user_usec 1\n")

    with pytest.raises(ValueError, match="usage_usec"):
        build.read_cpu_seconds(root)


class _Script:
    """Scripted clock and working-set readings for driving a meter by hand."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.now = 0.0

    def at(self, seconds: float, working_set: int) -> None:
        self.now = seconds
        (self.root / "memory.current").write_text(str(working_set))
        (self.root / "memory.stat").write_text("inactive_file 0\n")


def _meter(tmp_path) -> tuple[object, _Script]:
    script = _Script(_cgroup(tmp_path / "cg"))
    walls = iter(
        [
            datetime(2026, 9, 25, 22, 45, 41, tzinfo=UTC),
            datetime(2026, 9, 25, 22, 46, 56, tzinfo=UTC),
        ]
    )
    meter = build.UsageMeter(
        script.root,
        # Long enough that the background thread never ticks during a test.
        interval=3600,
        clock=lambda: script.now,
        wall=lambda: next(walls),
    )
    return meter, script


def test_working_set_is_integrated_over_the_run(tmp_path):
    meter, script = _meter(tmp_path)
    script.at(0, 100)
    meter.start()
    script.at(2, 300)
    meter.sample()
    script.at(4, 300)
    meter.sample()
    script.at(10, 0)

    usage = meter.finish()

    # Trapezoids: (100+300)/2*2 + 300*2 + (300+0)/2*6
    assert usage["memory_byte_seconds"] == 400 + 600 + 900


def test_the_report_carries_cpu_peak_and_the_run(tmp_path):
    meter, script = _meter(tmp_path)
    script.at(0, 0)
    meter.start()
    script.at(75, 0)

    assert meter.finish() == {
        "cpu_seconds": 41.2,
        "memory_byte_seconds": 0,
        "memory_peak_bytes": 812_000_000,
        "started_at": "2026-09-25T22:45:41.000Z",
        "finished_at": "2026-09-25T22:46:56.000Z",
    }


def test_an_unreadable_cgroup_reports_nothing(tmp_path):
    """A partial integral would under-bill silently; no report is estimated instead."""
    meter, script = _meter(tmp_path)
    script.at(0, 100)
    meter.start()
    (script.root / "memory.current").unlink()
    meter.sample()
    script.at(10, 100)

    assert meter.finish() is None


def test_the_background_thread_samples_and_stops(tmp_path):
    root = _cgroup(tmp_path / "cg")
    meter = build.UsageMeter(root, interval=0.01)
    meter.start()
    time.sleep(0.1)

    usage = meter.finish()

    assert usage is not None and usage["memory_byte_seconds"] > 0
    assert not meter._thread.is_alive()


def _run_main(monkeypatch, tmp_path, failure: Exception | None) -> dict:
    """`main` with every stage stubbed out, succeeding or raising `failure`."""
    _arrange_build(monkeypatch, tmp_path, dockerfile=True)
    monkeypatch.setattr(build, "CGROUP_ROOT", _cgroup(tmp_path / "cg"))

    def _build(**kwargs):
        if failure is not None:
            raise failure

    monkeypatch.setattr(build, "build_and_push_dockerfile", _build)

    build.main()
    return json.loads((tmp_path / "term").read_text())


@pytest.mark.parametrize(
    "failure, outcome",
    [
        (None, "image"),
        (build.BuildFailure("stack detection failed"), "error"),
        (RuntimeError("boom"), "error"),
    ],
    ids=["success", "build-failure", "unexpected-exception"],
)
def test_every_exit_path_reports_usage(monkeypatch, tmp_path, failure, outcome):
    payload = _run_main(monkeypatch, tmp_path, failure)

    assert outcome in payload
    assert payload["usage"]["cpu_seconds"] == 41.2
    assert set(payload["usage"]) == {
        "cpu_seconds", "memory_byte_seconds", "memory_peak_bytes", "started_at", "finished_at",
    }


def test_the_message_stays_under_the_termination_limit(monkeypatch, tmp_path):
    payload = _run_main(monkeypatch, tmp_path, build.BuildFailure("x" * 100_000))

    assert len(json.dumps(payload).encode()) < 4096
    assert "usage" in payload


# ---------------------------------------------------------------------------
# Environment contract
# ---------------------------------------------------------------------------


def test_a_missing_required_variable_is_named(monkeypatch):
    monkeypatch.delenv("CAELUS_ARTIFACT_URL", raising=False)

    with pytest.raises(build.BuildFailure, match="CAELUS_ARTIFACT_URL"):
        build._env("CAELUS_ARTIFACT_URL")


def test_an_empty_required_variable_counts_as_missing(monkeypatch):
    monkeypatch.setenv("CAELUS_REGISTRY", "")

    with pytest.raises(build.BuildFailure, match="CAELUS_REGISTRY"):
        build._env("CAELUS_REGISTRY")


def test_optional_integers_fall_back_and_validate(monkeypatch):
    monkeypatch.delenv("CAELUS_ARCHIVE_MAX_ENTRIES", raising=False)
    assert build._env_int("CAELUS_ARCHIVE_MAX_ENTRIES", 77) == 77

    monkeypatch.setenv("CAELUS_ARCHIVE_MAX_ENTRIES", "5")
    assert build._env_int("CAELUS_ARCHIVE_MAX_ENTRIES", 77) == 5

    monkeypatch.setenv("CAELUS_ARCHIVE_MAX_ENTRIES", "lots")
    with pytest.raises(build.BuildFailure, match="must be an integer"):
        build._env_int("CAELUS_ARCHIVE_MAX_ENTRIES", 77)


def test_main_exits_non_zero_without_an_artifact_url(monkeypatch, tmp_path):
    for name in (
        "CAELUS_ARTIFACT_URL",
        "CAELUS_USER_ID",
        "CAELUS_BUILD_ID",
        "CAELUS_REGISTRY",
        "CAELUS_REGISTRY_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CAELUS_TERMINATION_LOG", str(tmp_path / "term"))

    assert build.main() == 1
    assert "image" not in json.loads((tmp_path / "term").read_text())


# ---------------------------------------------------------------------------
# The version-matched pair
# ---------------------------------------------------------------------------


def test_the_frontend_image_is_pinned_by_digest():
    """A tag here would silently decouple the frontend from the railpack binary
    whose plan format it has to understand."""
    assert "@sha256:" in build.FRONTEND_IMAGE
    _, digest = build.FRONTEND_IMAGE.split("@", 1)
    assert len(digest) == len("sha256:") + 64


def test_the_builder_image_setting_carries_no_version_literal():
    """The builder's version lives in Terraform, not here. A default naming a
    real image would be a second place to bump, and the one nobody remembers."""
    from app.config import CaelusSettings

    assert CaelusSettings(_env_file=None).builder_image == ""


# ---------------------------------------------------------------------------
# The per-owner layer cache
# ---------------------------------------------------------------------------


def _captured_buildctl(monkeypatch, **overrides) -> list[str]:
    """Run `build_and_push` against a stubbed `_run` and return the argv."""
    captured: list[list[str]] = []
    monkeypatch.setattr(
        build, "_run", lambda command, *, stage, env=None: captured.append(command)
    )

    kwargs = {
        "source": Path("/work/src"),
        "plan_dir": Path("/work/plan"),
        "metadata_file": Path("/work/metadata.json"),
        "image_ref": "registry.home/7:some-build-id",
        "cache_key": "7",
        "cache_image_ref": build.cache_ref("registry.home", "7"),
        "buildkitd_flags": ["--config", "/work/buildkitd.toml"],
    }
    kwargs.update(overrides)
    build.build_and_push(**kwargs)

    assert len(captured) == 1
    return captured[0]


def _attrs(argv: list[str], flag: str) -> dict[str, str]:
    """Parse the comma-separated attribute list following `flag`."""
    value = argv[argv.index(flag) + 1]
    pairs = [item.split("=", 1) for item in value.split(",")]
    return {key: val for key, val in pairs}


def test_the_cache_ref_is_scoped_to_the_owner():
    """The whole isolation argument is that two owners cannot name the same
    ref. A cache one tenant can write and another can read is a way to hand a
    tenant's build a step result of your choosing."""
    assert build.cache_ref("registry.home", "7") != build.cache_ref(
        "registry.home", "8"
    )
    assert "/7:" in build.cache_ref("registry.home", "7")


def test_the_owner_alone_identifies_the_cache():
    """Each environment has its own registry, so dev user 1 and prod user 1
    never meet in one, and no environment discriminator belongs in the path."""
    assert build.cache_ref("cr.test", "1") == "cr.test/cache/1:latest"


def test_the_cache_lives_in_the_registry_the_image_is_pushed_to():
    """Cross-repository mounting is what keeps a cache hit from turning into a
    download and re-upload of layers the registry already holds."""
    assert build.cache_ref("registry.home", "7").startswith("registry.home/")


def test_the_build_imports_and_exports_the_owner_cache(monkeypatch):
    argv = _captured_buildctl(monkeypatch)

    assert "--import-cache" in argv
    assert "--export-cache" in argv

    imported = _attrs(argv, "--import-cache")
    exported = _attrs(argv, "--export-cache")
    assert imported["type"] == exported["type"] == "registry"
    # Reading and writing the same ref is what makes it a cache rather than a
    # one-way seed.
    assert imported["ref"] == exported["ref"] == build.cache_ref("registry.home", "7")


def test_the_cache_export_records_intermediate_steps(monkeypatch):
    """mode=min would only record the runtime image's own layers. The costly
    step is dependency installation, which never reaches the runtime image, so
    min would leave the expensive half of every build uncached."""
    assert _attrs(_captured_buildctl(monkeypatch), "--export-cache")["mode"] == "max"


def test_the_cache_export_cannot_fail_an_already_pushed_build(monkeypatch):
    """The image is pushed before the cache is written. A full or briefly
    unreachable registry must cost the build its cache, not its result."""
    assert _attrs(_captured_buildctl(monkeypatch), "--export-cache")["ignore-error"] == "true"


def test_the_cache_export_uses_a_manifest_a_plain_registry_accepts(monkeypatch):
    """Without these the exporter writes a manifest type the internal
    distribution registry rejects, and every export fails — silently, since
    ignore-error swallows it."""
    exported = _attrs(_captured_buildctl(monkeypatch), "--export-cache")
    assert exported["image-manifest"] == "true"
    assert exported["oci-mediatypes"] == "true"


def test_nothing_the_build_sends_to_the_registry_skips_verification(monkeypatch):
    """The capability travels as a bearer token, so an unverified connection
    would be a way to capture it (tenant-image-registry)."""
    argv = _captured_buildctl(monkeypatch)
    for flag in ("--import-cache", "--export-cache", "--output"):
        assert "registry.insecure" not in _attrs(argv, flag), flag


def test_the_cache_ref_reaching_buildctl_is_the_one_it_was_given(monkeypatch):
    """`build_and_push` must not re-derive the ref from anything of its own —
    `main` computes it from the platform-supplied owner and that is the only
    input that may decide it."""
    argv = _captured_buildctl(monkeypatch, cache_image_ref="registry.home/cache/99:latest")
    assert _attrs(argv, "--import-cache")["ref"] == "registry.home/cache/99:latest"
    assert _attrs(argv, "--export-cache")["ref"] == "registry.home/cache/99:latest"


# ---------------------------------------------------------------------------
# The ghcr.io mirror
# ---------------------------------------------------------------------------

MIRROR_SCRIPT = REPO_ROOT / "scripts" / "mirror-railpack-images.sh"


def _buildkitd_config(registry: str = "registry.home") -> dict:
    return tomllib.loads(build.buildkitd_config(registry))


def test_the_generated_daemon_config_is_valid_toml():
    """buildkitd refuses to start on a malformed config, which in a build pod
    surfaces as a connection timeout rather than a parse error."""
    assert _buildkitd_config()["registry"]


def test_ghcr_is_mirrored_to_the_supplied_registry():
    """The mirror host follows CAELUS_REGISTRY rather than being baked in, so
    the registry is named in one place and cannot drift out of agreement with
    the image push and the cache."""
    config = _buildkitd_config("some.registry")
    assert config["registry"]["ghcr.io"]["mirrors"] == ["some.registry"]


def test_the_mirror_is_reached_over_a_verified_connection():
    """BuildKit reads a mirror's TLS settings from that mirror's *own* section.
    There is none: the registry's certificate verifies, and a pull from it
    carries the build's capability."""
    assert "some.registry" not in _buildkitd_config("some.registry")["registry"]


def test_only_ghcr_is_mirrored():
    """A build reaches PyPI, npm and crates.io while running tenant code.
    Redirecting those through our registry would be a different feature with a
    different threat model; this one covers the images pulled before any tenant
    code runs."""
    registries = _buildkitd_config()["registry"]

    assert [host for host, cfg in registries.items() if cfg.get("mirrors")] == ["ghcr.io"]


def test_the_config_is_written_where_the_returned_flags_point(tmp_path):
    """The flag is passed explicitly because buildkitd's default config path
    differs between rootless and root mode."""
    flags = build.write_buildkitd_config(tmp_path / "nested" / "buildkitd.toml", "registry.home")

    assert flags[0] == "--config"
    written = Path(flags[1])
    assert written.is_file()
    assert tomllib.loads(written.read_text())["registry"]["ghcr.io"]["mirrors"]


def test_the_daemon_flags_keep_the_ones_the_image_set(monkeypatch):
    """`--oci-worker-no-process-sandbox` comes from the image's ENV and rootless
    buildkitd does not start without it. Assigning BUILDKITD_FLAGS instead of
    appending would drop it."""
    monkeypatch.setenv("BUILDKITD_FLAGS", "--oci-worker-no-process-sandbox")

    flags = build.buildkitd_env(["--config", "/somewhere.toml"])["BUILDKITD_FLAGS"].split()

    assert "--oci-worker-no-process-sandbox" in flags
    assert flags[-2:] == ["--config", "/somewhere.toml"]


def test_the_daemon_flags_survive_an_image_that_sets_none(monkeypatch):
    monkeypatch.delenv("BUILDKITD_FLAGS", raising=False)

    assert build.buildkitd_env(["--config", "/x.toml"])["BUILDKITD_FLAGS"] == "--config /x.toml"


def test_the_daemon_flags_reach_the_spawned_buildkitd(monkeypatch):
    """`buildctl-daemonless.sh` reads BUILDKITD_FLAGS from its environment and
    word-splits it into the daemon. A config the daemon never sees means every
    build silently keeps pulling from ghcr.io."""
    monkeypatch.setenv("BUILDKITD_FLAGS", "--oci-worker-no-process-sandbox")
    seen: list[dict[str, str]] = []
    monkeypatch.setattr(
        build, "_run", lambda command, *, stage, env=None: seen.append(env or {})
    )

    build.build_and_push(
        source=Path("/work/src"),
        plan_dir=Path("/work/plan"),
        metadata_file=Path("/work/metadata.json"),
        image_ref="registry.home/7:b",
        cache_key="7",
        cache_image_ref=build.cache_ref("registry.home", "7"),
        buildkitd_flags=["--config", "/work/buildkitd.toml"],
    )

    assert seen[0]["BUILDKITD_FLAGS"].split() == [
        "--oci-worker-no-process-sandbox",
        "--config",
        "/work/buildkitd.toml",
    ]


def test_the_mirror_script_pins_the_frontend_build_py_names():
    """The script mirrors the frontend by tag; build.py names it by digest. If
    they disagree the mirror holds an image nothing ever asks for, and every
    build keeps pulling the frontend from ghcr.io without saying so."""
    assert MIRROR_SCRIPT.is_file(), f"mirror script not found at {MIRROR_SCRIPT}"
    script = MIRROR_SCRIPT.read_text()

    _, pinned_digest = build.FRONTEND_IMAGE.split("@", 1)
    assert f"FRONTEND_DIGEST={pinned_digest}" in script


def test_the_mirror_script_pins_the_railpack_version_the_dockerfile_builds():
    """Same version-matched set as the binary and the frontend: a mirror of the
    wrong release's base images is never consulted."""
    dockerfile = (REPO_ROOT / "products" / "custom" / "builder" / "Dockerfile").read_text()
    version = next(
        line.split("=", 1)[1].strip()
        for line in dockerfile.splitlines()
        if line.startswith("ARG RAILPACK_VERSION=")
    )

    assert f"RAILPACK_VERSION={version}" in MIRROR_SCRIPT.read_text()


# ---------------------------------------------------------------------------
# Builder selection
# ---------------------------------------------------------------------------


def test_a_root_dockerfile_selects_itself(tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM scratch\n")
    assert build.select_builder(tmp_path) == "dockerfile"


def test_no_dockerfile_selects_detection(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    assert build.select_builder(tmp_path) == "railpack"


def test_a_dockerfile_below_the_root_is_not_the_projects_answer(tmp_path):
    """A Dockerfile deeper in the tree belongs to something else — a
    sub-service, a fixture — and must not decide how the project is built."""
    (tmp_path / "svc").mkdir()
    (tmp_path / "svc" / "Dockerfile").write_text("FROM scratch\n")
    assert build.select_builder(tmp_path) == "railpack"


def test_a_directory_named_dockerfile_is_not_a_dockerfile(tmp_path):
    (tmp_path / "Dockerfile").mkdir()
    assert build.select_builder(tmp_path) == "railpack"


# ---------------------------------------------------------------------------
# The Dockerfile build
# ---------------------------------------------------------------------------


def _captured_dockerfile_buildctl(monkeypatch, **overrides) -> list[str]:
    """Run `build_and_push_dockerfile` against a stubbed `_run`, return argv."""
    captured: list[list[str]] = []
    monkeypatch.setattr(
        build, "_run", lambda command, *, stage, env=None: captured.append(command)
    )

    kwargs = {
        "source": Path("/work/src"),
        "metadata_file": Path("/work/metadata.json"),
        "image_ref": "registry.home/7:some-build-id",
        "cache_image_ref": build.cache_ref("registry.home", "7"),
        "registry": "registry.home",
        "buildkitd_flags": ["--config", "/work/buildkitd.toml"],
    }
    kwargs.update(overrides)
    build.build_and_push_dockerfile(**kwargs)

    assert len(captured) == 1
    return captured[0]


def test_the_dockerfile_build_reads_the_project_as_both_context_and_dockerfile(monkeypatch):
    argv = _captured_dockerfile_buildctl(monkeypatch)

    assert "--frontend=dockerfile.v0" in argv
    assert "filename=Dockerfile" in argv
    locals_given = [argv[i + 1] for i, arg in enumerate(argv) if arg == "--local"]
    assert locals_given == ["context=/work/src", "dockerfile=/work/src"]


def test_the_dockerfile_frontend_is_pinned_by_digest():
    """A tag would let whoever can write that repository choose the code that
    drives the build daemon. A digest makes a substituted image fail closed."""
    assert build.DOCKERFILE_FRONTEND_DIGEST.startswith("sha256:")
    assert len(build.DOCKERFILE_FRONTEND_DIGEST) == len("sha256:") + 64


def test_the_syntax_directive_is_overridden_by_the_pinned_frontend(monkeypatch):
    """Whatever interprets a Dockerfile is a client of the build daemon, not a
    build step: it emits its own LLB, names its own cache imports and sits on
    the daemon's image-resolution path. A `# syntax=` directive would let the
    tenant pick it."""
    argv = _captured_dockerfile_buildctl(monkeypatch)

    syntax = next(
        arg for arg in argv if arg.startswith("build-arg:BUILDKIT_SYNTAX=")
    ).split("=", 1)[1]
    assert syntax == f"registry.home/docker/dockerfile@{build.DOCKERFILE_FRONTEND_DIGEST}"


def test_the_pinned_frontend_is_addressed_at_the_supplied_registry(monkeypatch):
    """Named at the internal registry rather than Docker Hub, and without a
    docker.io mirror entry that would route every tenant pull through it."""
    argv = _captured_dockerfile_buildctl(monkeypatch, registry="some.registry")

    assert any(
        arg == f"build-arg:BUILDKIT_SYNTAX=some.registry/docker/dockerfile@{build.DOCKERFILE_FRONTEND_DIGEST}"
        for arg in argv
    )


def test_both_builders_publish_and_cache_identically(monkeypatch):
    """The cache ref is an isolation boundary and the output is where the
    platform will look for the image. Neither may depend on which frontend
    produced the LLB."""
    railpack = _captured_buildctl(monkeypatch)
    dockerfile = _captured_dockerfile_buildctl(monkeypatch)

    for flag in ("--import-cache", "--export-cache", "--output", "--metadata-file"):
        assert railpack[railpack.index(flag) + 1] == dockerfile[dockerfile.index(flag) + 1]
    assert "--progress=plain" in dockerfile


def test_the_dockerfile_build_carries_no_cache_key_and_no_entitlements(monkeypatch):
    """cache-key namespaces the *Railpack* frontend's mount caches and means
    nothing here. `--allow` would widen what tenant code may do."""
    argv = _captured_dockerfile_buildctl(monkeypatch)

    assert not any(arg.startswith("build-arg:cache-key=") for arg in argv)
    assert not any(arg.startswith("--allow") for arg in argv)


def test_the_mirror_script_pins_the_dockerfile_frontend_build_py_names():
    """build.py addresses this one at the internal registry with no upstream to
    fall through to, so a disagreement here is a broken build, not a slow one."""
    script = MIRROR_SCRIPT.read_text()
    assert f"DOCKERFILE_FRONTEND_DIGEST={build.DOCKERFILE_FRONTEND_DIGEST}" in script


# ---------------------------------------------------------------------------
# The runtime contract check
# ---------------------------------------------------------------------------


def test_the_platform_port_matches_the_chart():
    """The builder cannot see the chart, so this constant is a second copy of
    its containerPort. Drift would make the warning lie."""
    values = (
        REPO_ROOT / "products" / "custom" / "chart" / "values.yaml"
    ).read_text()
    declared = next(
        line.split(":", 1)[1].strip()
        for line in values.splitlines()
        if line.startswith("containerPort:")
    )
    assert str(build.PLATFORM_PORT) == declared


def test_an_image_declaring_another_port_is_warned_about(capsys):
    build.warn_about_runtime_contract({"ExposedPorts": {"80/tcp": {}}, "Cmd": ["nginx"]})

    out = capsys.readouterr().out
    assert "WARNING" in out and "80/tcp" in out and str(build.PLATFORM_PORT) in out


def test_an_image_with_nothing_to_run_is_warned_about(capsys):
    build.warn_about_runtime_contract({"ExposedPorts": {"8080/tcp": {}}})

    out = capsys.readouterr().out
    assert "WARNING" in out and "nothing to run" in out


def test_a_conforming_image_is_not_warned_about(capsys):
    build.warn_about_runtime_contract(
        {"ExposedPorts": {"8080/tcp": {}}, "Entrypoint": ["/app/server"]}
    )

    assert "WARNING" not in capsys.readouterr().out


def test_an_image_declaring_no_ports_is_not_warned_about(capsys):
    """Every Railpack-built image declares none — nothing in its plan emits
    EXPOSE — so warning here would fire on nearly every build and teach people
    to skip the warning that means something."""
    build.warn_about_runtime_contract({"Cmd": ["node", "server.js"]})

    assert "WARNING" not in capsys.readouterr().out


def test_an_uninspectable_image_is_not_warned_about(capsys):
    """A warning that could not be computed must not become a warning."""
    build.warn_about_runtime_contract(None)

    assert "WARNING" not in capsys.readouterr().out


def _stub_registry(monkeypatch, documents: dict[str, dict]):
    """Serve `documents` keyed by the trailing path of the registry URL."""
    requested: list[str] = []

    class _Response(io.BytesIO):
        def close(self):  # noqa: D102 — contextlib.closing calls this
            super().close()

    def _urlopen(request, timeout=None, context=None):
        url = request.full_url if hasattr(request, "full_url") else request
        requested.append(url)
        for suffix, document in documents.items():
            if url.endswith(suffix):
                return _Response(json.dumps(document).encode())
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr(build.urllib.request, "urlopen", _urlopen)
    return requested


def test_the_image_config_is_read_back_from_the_registry(monkeypatch):
    """Read back rather than parsed out of the Dockerfile: EXPOSE is often
    inherited from a base image, and the registry holds what will actually
    run."""
    requested = _stub_registry(
        monkeypatch,
        {
            "manifests/sha256:aa": {"config": {"digest": "sha256:bb"}},
            "blobs/sha256:bb": {"config": {"ExposedPorts": {"8080/tcp": {}}}},
        },
    )

    config = build.read_image_config("registry.home", "u/7", "sha256:aa", "tok")

    assert config == {"ExposedPorts": {"8080/tcp": {}}}
    assert requested[0].startswith("https://registry.home/v2/u/7/")


def test_the_image_config_is_read_with_the_capability_over_verified_tls(monkeypatch):
    seen: list[tuple] = []

    def _urlopen(request, timeout=None, context=None):
        seen.append((request.get_header("Authorization"), context))
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(build.urllib.request, "urlopen", _urlopen)
    build.read_image_config("cr.test", "u/7", "sha256:aa", "tok")

    assert seen == [("Bearer tok", None)]


def test_an_index_is_followed_to_the_platforms_manifest(monkeypatch):
    _stub_registry(
        monkeypatch,
        {
            "manifests/sha256:aa": {
                "manifests": [
                    {"digest": "sha256:arm", "platform": {"architecture": "arm64"}},
                    {"digest": "sha256:amd", "platform": {"architecture": "amd64"}},
                ]
            },
            "manifests/sha256:amd": {"config": {"digest": "sha256:bb"}},
            "blobs/sha256:bb": {"config": {"Cmd": ["/app"]}},
        },
    )

    assert build.read_image_config("registry.home", "u/7", "sha256:aa", "tok") == {"Cmd": ["/app"]}


def test_an_unreadable_image_config_is_not_a_build_failure(monkeypatch):
    """This feeds a warning. A warning that could fail a good build would be
    worse than no warning at all."""
    _stub_registry(monkeypatch, {})

    assert build.read_image_config("registry.home", "u/7", "sha256:aa", "tok") is None


# ---------------------------------------------------------------------------
# main(): which path runs, and what happens when it fails
# ---------------------------------------------------------------------------


def _arrange_build(monkeypatch, tmp_path, *, dockerfile: bool):
    """Point main() at a prepared source tree with every side effect stubbed."""
    source = tmp_path / "src"
    source.mkdir(exist_ok=True)
    (source / "package.json").write_text("{}")
    if dockerfile:
        (source / "Dockerfile").write_text("FROM scratch\n")

    for name, value in {
        "CAELUS_ARTIFACT_URL": "https://store/one",
        "CAELUS_USER_ID": "7",
        "CAELUS_BUILD_ID": "b-1",
        "CAELUS_REGISTRY": "registry.home",
        "CAELUS_REGISTRY_TOKEN": "capability",
        "CAELUS_WORKDIR": str(tmp_path),
        # main() points this at the capability it writes; registered here so
        # the test restores it rather than leaking it into later tests.
        "DOCKER_CONFIG": str(tmp_path / "unused"),
        "CAELUS_TERMINATION_LOG": str(tmp_path / "term"),
    }.items():
        monkeypatch.setenv(name, value)

    # The archive is already on disk, so extraction is the one step to skip;
    # `main` deletes and re-creates the tree, so re-plant it here.
    @contextlib.contextmanager
    def _artifact(*args, **kwargs):
        yield io.BytesIO(b"")

    def _extract(*args, **kwargs):
        source.mkdir(exist_ok=True)
        (source / "package.json").write_text("{}")
        if dockerfile:
            (source / "Dockerfile").write_text("FROM scratch\n")

    monkeypatch.setattr(build, "open_artifact", _artifact)
    monkeypatch.setattr(build, "extract_stream", _extract)
    monkeypatch.setattr(build, "write_buildkitd_config", lambda path, registry: [])
    monkeypatch.setattr(build, "read_digest", lambda path: "sha256:" + "c" * 64)
    monkeypatch.setattr(build, "read_image_config", lambda *a, **k: None)

    calls: list[str] = []
    monkeypatch.setattr(build, "prepare_plan", lambda *a, **k: calls.append("prepare"))
    monkeypatch.setattr(build, "build_and_push", lambda **k: calls.append("railpack"))
    monkeypatch.setattr(
        build, "build_and_push_dockerfile", lambda **k: calls.append("dockerfile")
    )
    return calls


def test_a_project_with_a_dockerfile_never_runs_detection(monkeypatch, tmp_path, capsys):
    calls = _arrange_build(monkeypatch, tmp_path, dockerfile=True)

    assert build.main() == 0
    assert calls == ["dockerfile"], "stack detection must not run for a Dockerfile build"
    assert "Dockerfile" in capsys.readouterr().out


def test_a_project_without_one_is_built_exactly_as_before(monkeypatch, tmp_path, capsys):
    calls = _arrange_build(monkeypatch, tmp_path, dockerfile=False)

    assert build.main() == 0
    assert calls == ["prepare", "railpack"]
    assert "detecting the project's stack" in capsys.readouterr().out.lower()


def test_a_failing_dockerfile_build_does_not_fall_back_to_detection(
    monkeypatch, tmp_path
):
    """A project that builds one way today and another tomorrow, depending on
    whether its Dockerfile happened to compile, is indistinguishable from a
    platform fault."""
    calls = _arrange_build(monkeypatch, tmp_path, dockerfile=True)

    def _fail(**kwargs):
        calls.append("dockerfile")
        raise build.BuildFailure("dockerfile parse error")

    monkeypatch.setattr(build, "build_and_push_dockerfile", _fail)

    assert build.main() == 1
    assert calls == ["dockerfile"]
    assert "image" not in json.loads((tmp_path / "term").read_text())


def test_the_contract_warning_runs_for_both_builders(monkeypatch, tmp_path, capsys):
    """A detected image can miss the port contract just as easily as a
    hand-written one."""
    for dockerfile in (True, False):
        _arrange_build(monkeypatch, tmp_path, dockerfile=dockerfile)
        monkeypatch.setattr(
            build,
            "read_image_config",
            lambda *a, **k: {"ExposedPorts": {"3000/tcp": {}}, "Cmd": ["x"]},
        )

        assert build.main() == 0
        assert "WARNING" in capsys.readouterr().out


def test_the_build_pushes_to_the_owners_repository_with_its_capability(monkeypatch, tmp_path):
    _arrange_build(monkeypatch, tmp_path, dockerfile=False)
    pushed: dict = {}
    inspected: list[tuple] = []
    monkeypatch.setattr(build, "build_and_push", lambda **k: pushed.update(k))
    monkeypatch.setattr(build, "read_image_config", lambda *a: inspected.append(a))

    assert build.main() == 0
    assert pushed["image_ref"] == "registry.home/u/7:b-1"
    assert pushed["cache_image_ref"] == "registry.home/cache/7:latest"
    config = json.loads((Path(os.environ["DOCKER_CONFIG"]) / "config.json").read_text())
    assert config == {"auths": {"registry.home": {"registrytoken": "capability"}}}
    assert inspected == [("registry.home", "u/7", "sha256:" + "c" * 64, "capability")]
    assert json.loads((tmp_path / "term").read_text()) == {"image": "7@sha256:" + "c" * 64}


def test_the_capability_file_is_readable_by_its_owner_alone(tmp_path):
    directory = build.write_docker_config(tmp_path / "docker", "cr.test", "tok")
    path = directory / "config.json"

    assert json.loads(path.read_text()) == {"auths": {"cr.test": {"registrytoken": "tok"}}}
    assert path.stat().st_mode & 0o777 == 0o600
