"""`freepod bucket`: the deployment's bucket, and the objects in it.

The platform is scripted; the bucket is an in-memory S3 shaped like Garage
(`fake_s3.FakeS3`). Signing is covered in `test_s3.py` and against a real
Garage in `test_s3_garage.py`.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from freepod import EXIT_ERROR, EXIT_OK, EXIT_USAGE, objects, s3
from freepod.bucket import NO_BUCKET_CODE
from freepod.cli import main

from conftest import json_response
from fake_s3 import BUCKET, FakeS3, Stream
from test_deploy import project_at
from test_vars import POINTER, _StubSession, httpx_client

GIGABYTE = 1024 ** 3
SECRET = "3cf36d6b8f77b0c3c1e46ee2db900d9f5d77303366a93d32a00c6aab017f7f41"
ACCESS_KEY_ID = "GK7336a630a8a03ea0bd05cf73"


def details(**overrides):
    body = {
        "bucket": BUCKET,
        "endpoint": "https://blob.example.test",
        "region": "garage",
        "access_key_id": ACCESS_KEY_ID,
        "secret_access_key": SECRET,
        "secret_withheld": False,
        "usage": {
            "bytes": 3 * 1024 ** 2,
            "objects": 5,
            "max_size_bytes": GIGABYTE,
            "max_objects": 1_000_000,
        },
    }
    body.update(overrides)
    return body


class Platform:
    """A platform serving one deployment's bucket details."""

    def __init__(self, *, body=None, status=200):
        self.body = details() if body is None else body
        self.status = status
        self.queries = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/me":
            return json_response(200, {"id": 7, "email": "dev@example.com"})
        if re.fullmatch(r"/api/users/7/deployments/[^/]+/bucket", path):
            self.queries.append(dict(request.url.params))
            return json_response(self.status, self.body)
        return json_response(404, {"detail": f"unrouted {request.method} {path}"})


@pytest.fixture
def store():
    return FakeS3()


@pytest.fixture
def work(tmp_path):
    path = tmp_path / "work"
    path.mkdir()
    return path


@pytest.fixture
def run(monkeypatch, tmp_path, store):
    """Drive `main(['bucket', ...])` in a project at `tmp_path`."""

    real_bucket = s3.Bucket

    def go(argv, *, platform=None, pointer=POINTER, global_args=()):
        platform = platform or Platform()
        project_at(tmp_path, pointer=pointer)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("freepod.cli.Context.session", lambda self, force_flow=None: _StubSession())
        monkeypatch.setattr("freepod.cli.Context.client", lambda self, session: httpx_client(platform))
        monkeypatch.setattr(
            "freepod.cli.s3_module.Bucket",
            lambda creds, verbose=False: real_bucket(
                creds, verbose=verbose, client=store.client(), retry_delay=0
            ),
        )
        return main([*global_args, "bucket", *argv])

    return go


@pytest.fixture
def small_parts(monkeypatch):
    """Multipart above 1 KiB in 1 KiB parts, so tests need not write megabytes."""
    monkeypatch.setattr(objects, "SINGLE_PUT_MAX", 1024)
    monkeypatch.setattr(objects, "PART_SIZE", 1024)


# ── status ──────────────────────────────────────────────────────────────────


def test_status_reports_the_bucket_with_the_secret_masked(run, capsys):
    assert run(["status"]) == EXIT_OK
    out = capsys.readouterr().out
    rows = dict(re.findall(r"^(\w[\w ]*?)\s{2,}(.+)$", out, re.M))
    assert rows["Bucket"] == BUCKET
    assert rows["Endpoint"] == "https://blob.example.test"
    assert rows["Region"] == "garage"
    assert rows["Access key"] == ACCESS_KEY_ID
    assert SECRET not in out
    assert "--show-secret" in out
    assert "3 MB of 1.0 GB" in out
    assert "5 of 1,000,000" in out


def test_status_shows_the_secret_when_asked(run, capsys):
    assert run(["status", "--show-secret"]) == EXIT_OK
    assert SECRET in capsys.readouterr().out


def test_the_mask_does_not_reveal_the_secrets_length(run, capsys):
    run(["status"])
    first = capsys.readouterr().out
    platform = Platform(body=details(secret_access_key="short"))
    run(["status"], platform=platform)
    second = capsys.readouterr().out
    mask = re.compile(r"Secret key\s+(\S+)")
    assert mask.search(first).group(1) == mask.search(second).group(1)


def test_status_says_a_withheld_secret_is_withheld(run, capsys):
    platform = Platform(body=details(secret_access_key=None, secret_withheld=True))
    assert run(["status", "--show-secret"], platform=platform) == EXIT_OK
    out = capsys.readouterr().out
    assert "withheld" in out
    assert "--show-secret to reveal" not in out


def test_status_asks_for_usage(run):
    platform = Platform()
    run(["status"], platform=platform)
    assert platform.queries == [{}]


def test_a_deployment_without_a_bucket_is_not_an_error_for_status(run, capsys):
    platform = Platform(body={"detail": "no", "code": NO_BUCKET_CODE}, status=404)
    assert run(["status"], platform=platform) == EXIT_OK
    assert "no bucket" in capsys.readouterr().err


def test_status_needs_a_deployment(run, capsys):
    assert run(["status"], pointer=None) == EXIT_USAGE
    assert "records no deployment" in capsys.readouterr().err


# ── credentials for the object commands ─────────────────────────────────────


def test_object_commands_skip_usage(run, store):
    platform = Platform()
    assert run(["ls"], platform=platform) == EXIT_OK
    assert platform.queries == [{"usage": "false"}]


def test_object_commands_need_a_bucket(run, store, capsys):
    platform = Platform(body={"detail": "no", "code": NO_BUCKET_CODE}, status=404)
    assert run(["ls"], platform=platform) == EXIT_ERROR
    assert "no bucket" in capsys.readouterr().err
    assert store.requests == []


def test_object_commands_refuse_a_withheld_secret_without_a_request(run, store, capsys):
    platform = Platform(body=details(secret_access_key=None, secret_withheld=True))
    assert run(["ls"], platform=platform) == EXIT_ERROR
    assert "owner alone" in capsys.readouterr().err
    assert store.requests == []


def test_nothing_on_disk_holds_the_secret(run, store, work, isolated_home, tmp_path):
    (work / "f.txt").write_text("x")
    run(["cp", str(work / "f.txt"), ":f.txt"])
    run(["cp", ":f.txt", str(work / "g.txt")])
    for root in (isolated_home, tmp_path):
        for path in Path(root).rglob("*"):
            if path.is_file():
                assert SECRET.encode() not in path.read_bytes(), path


def test_verbose_output_carries_no_secret(run, store, work, capsys):
    (work / "f.txt").write_text("x")
    assert run(["cp", str(work / "f.txt"), ":f.txt"], global_args=["--verbose"]) == EXIT_OK
    err = capsys.readouterr().err
    assert "s3: PUT" in err
    assert SECRET not in err and "Signature=" not in err


# ── remote paths ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "arg, required, expected",
    [
        (":", True, ""),
        (":/", True, ""),
        (":a/b", True, "a/b"),
        (":/a/b", True, "a/b"),
        ("a/b", True, None),
        ("a/b", False, "a/b"),
        ("/a/b", False, "a/b"),
        (":dir/", True, "dir/"),
    ],
)
def test_remote_paths(arg, required, expected):
    assert objects.remote_path(arg, marker_required=required) == expected


def test_a_leading_slash_names_the_same_key(run, store, capsysbinary):
    store.put("a/b.txt", b"hello")
    assert run(["cat", ":/a/b.txt"]) == EXIT_OK
    assert capsysbinary.readouterr().out == b"hello"


def test_cp_with_neither_side_marked_is_refused_without_a_request(run, store, capsys):
    assert run(["cp", "a.txt", "b.txt"]) == EXIT_USAGE
    assert "Mark the bucket's side" in capsys.readouterr().err
    assert store.requests == []


def test_the_object_wins_over_a_prefix_of_the_same_name(run, store, capsysbinary):
    store.put("x", b"object")
    store.put("x/inside", b"prefixed")
    assert run(["cat", ":x"]) == EXIT_OK
    assert capsysbinary.readouterr().out == b"object"
    assert run(["ls", ":x/"]) == EXIT_OK
    assert capsysbinary.readouterr().out.decode().split() == ["inside"]


# ── ls ──────────────────────────────────────────────────────────────────────


def test_ls_lists_one_level(run, store, capsys):
    for key in ("a.txt", "img/1.png", "img/2.png"):
        store.put(key, b"x")
    assert run(["ls"]) == EXIT_OK
    assert capsys.readouterr().out.split() == ["a.txt", "img/"]


def test_ls_without_the_colon_is_still_the_bucket(run, store, capsys, tmp_path):
    (tmp_path / "img").mkdir()
    store.put("img/1.png", b"x")
    assert run(["ls", "img"]) == EXIT_OK
    assert capsys.readouterr().out.split() == ["1.png"]


def test_ls_recursive(run, store, capsys):
    for key in ("a.txt", "img/1.png", "img/sub/2.png"):
        store.put(key, b"x")
    assert run(["ls", "-r", ":img"]) == EXIT_OK
    assert capsys.readouterr().out.split() == ["1.png", "sub/2.png"]


def test_ls_long_shows_size_and_time(run, store, capsys):
    store.put("a.txt", b"12345")
    store.put("img/1.png", b"x")
    assert run(["ls", "-l"]) == EXIT_OK
    lines = capsys.readouterr().out.splitlines()
    assert re.match(r"\s+5  \d{4}-\d\d-\d\d \d\d:\d\d  a\.txt$", lines[0])
    assert lines[1].endswith("img/")


def test_ls_follows_pages(run, store, capsys):
    store.page_size = 2
    for n in range(5):
        store.put(f"k{n}", b"x")
    assert run(["ls"]) == EXIT_OK
    assert capsys.readouterr().out.split() == [f"k{n}" for n in range(5)]


def test_ls_of_an_empty_bucket_prints_nothing(run, store, capsys):
    assert run(["ls"]) == EXIT_OK
    assert capsys.readouterr().out == ""


def test_ls_of_a_missing_path_fails(run, store, capsys):
    assert run(["ls", ":nothing-here"]) == EXIT_ERROR
    assert "no such object or prefix" in capsys.readouterr().err


# ── cp ──────────────────────────────────────────────────────────────────────


def test_cp_a_file_into_a_prefix(run, store, work):
    (work / "photo.jpg").write_bytes(b"jpeg")
    assert run(["cp", str(work / "photo.jpg"), ":images/"]) == EXIT_OK
    assert store.objects == {"images/photo.jpg": b"jpeg"}


def test_cp_a_file_to_the_root(run, store, work):
    (work / "photo.jpg").write_bytes(b"jpeg")
    assert run(["cp", str(work / "photo.jpg"), ":"]) == EXIT_OK
    assert store.keys() == ["photo.jpg"]


def test_cp_a_file_to_an_exact_key(run, store, work):
    (work / "photo.jpg").write_bytes(b"jpeg")
    assert run(["cp", str(work / "photo.jpg"), ":images/cover.jpg"]) == EXIT_OK
    assert store.keys() == ["images/cover.jpg"]


def test_cp_a_directory_to_a_prefix(run, store, work):
    (work / "site" / "css").mkdir(parents=True)
    (work / "site" / "index.html").write_text("<h1>")
    (work / "site" / "css" / "main.css").write_text("body{}")
    (work / "site" / "empty").mkdir()
    assert run(["cp", str(work / "site"), ":public"]) == EXIT_OK
    assert store.keys() == ["public/css/main.css", "public/index.html"]


def test_cp_follows_file_symlinks_but_not_directory_symlinks(run, store, work, capsys):
    (work / "site").mkdir()
    (work / "elsewhere").mkdir()
    (work / "elsewhere" / "secret.txt").write_text("s")
    (work / "real.txt").write_text("r")
    (work / "site" / "link.txt").symlink_to(work / "real.txt")
    (work / "site" / "dir").symlink_to(work / "elsewhere")
    assert run(["cp", str(work / "site"), ":s"]) == EXIT_ERROR
    assert store.objects == {"s/link.txt": b"r"}
    assert "symlinked directory" in capsys.readouterr().err


def test_cp_a_prefix_to_a_local_directory(run, store, work):
    store.put("public/index.html", b"<h1>")
    store.put("public/css/main.css", b"body{}")
    assert run(["cp", ":public", str(work / "backup")]) == EXIT_OK
    assert (work / "backup" / "index.html").read_bytes() == b"<h1>"
    assert (work / "backup" / "css" / "main.css").read_bytes() == b"body{}"


def test_cp_an_object_into_an_existing_directory(run, store, work):
    store.put("public/index.html", b"<h1>")
    (work / "downloads").mkdir()
    assert run(["cp", ":public/index.html", str(work / "downloads")]) == EXIT_OK
    assert (work / "downloads" / "index.html").read_bytes() == b"<h1>"


def test_cp_an_object_to_an_exact_path(run, store, work):
    store.put("public/index.html", b"<h1>")
    assert run(["cp", ":public/index.html", str(work / "home.html")]) == EXIT_OK
    assert (work / "home.html").read_bytes() == b"<h1>"


def test_a_downloaded_file_gets_ordinary_permissions(run, store, work):
    store.put("f", b"x")
    old = os.umask(0o022)
    try:
        assert run(["cp", ":f", str(work / "f")]) == EXIT_OK
    finally:
        os.umask(old)
    assert (work / "f").stat().st_mode & 0o777 == 0o644


def test_cp_within_the_bucket_sends_no_object_bytes(run, store):
    store.put("public/a", b"A" * 100)
    store.put("public/b/c", b"C" * 100)
    assert run(["cp", ":public", ":public-old"]) == EXIT_OK
    assert store.keys() == ["public-old/a", "public-old/b/c", "public/a", "public/b/c"]
    assert sorted(store.copies) == [("public/a", "public-old/a"), ("public/b/c", "public-old/b/c")]
    assert store.bodies == []
    assert not [m for m, key, _q in store.requests if m == "GET" and key]


def test_cp_within_onto_itself_is_refused(run, store, capsys):
    store.put("a.txt", b"x")
    assert run(["cp", ":a.txt", ":a.txt"]) == EXIT_USAGE
    assert "onto itself" in capsys.readouterr().err


def test_cp_within_into_its_own_subtree_is_refused(run, store, capsys):
    store.put("a/x", b"x")
    assert run(["cp", ":a", ":a/b"]) == EXIT_USAGE
    assert "its own output" in capsys.readouterr().err


def test_cp_overwrites_without_asking(run, store, work):
    store.put("a.txt", b"old")
    (work / "a.txt").write_bytes(b"new")
    assert run(["cp", str(work / "a.txt"), ":a.txt"]) == EXIT_OK
    assert store.objects["a.txt"] == b"new"


def test_a_missing_local_source_is_refused_without_a_request(run, store, work, capsys):
    assert run(["cp", str(work / "nope"), ":x"]) == EXIT_ERROR
    assert "does not exist" in capsys.readouterr().err
    assert store.requests == []


# ── keys as local paths ─────────────────────────────────────────────────────


def test_keys_are_normalized_and_escapes_skipped(run, store, work, capsys):
    store.put("../../../../escape.txt", b"bad")
    store.put("foo/bar/../quux/file.txt", b"quux")
    store.put("./dot/file.txt", b"dot")
    store.put("ok.txt", b"ok")
    out = work / "out"

    assert run(["cp", ":", str(out)]) == EXIT_ERROR

    assert (out / "foo" / "quux" / "file.txt").read_bytes() == b"quux"
    assert (out / "dot" / "file.txt").read_bytes() == b"dot"
    assert (out / "ok.txt").read_bytes() == b"ok"
    assert not list(work.rglob("escape.txt"))
    err = capsys.readouterr().err
    assert "'../../../../escape.txt' would land outside" in err
    assert "1 item was not copied" in err


def test_two_keys_on_one_path_skip_the_second(run, store, work, capsys):
    store.put("a//double.txt", b"first")
    store.put("a/double.txt", b"second")
    assert run(["cp", ":", str(work / "out")]) == EXIT_ERROR
    assert (work / "out" / "a" / "double.txt").read_bytes() == b"first"
    assert "which an earlier key already wrote" in capsys.readouterr().err


def test_a_file_and_a_directory_of_one_name_skip_one(run, store, work, capsys):
    store.put("plain/a", b"file")
    store.put("plain/a/b", b"nested")
    assert run(["cp", ":", str(work / "out")]) == EXIT_ERROR
    assert "skipped:" in capsys.readouterr().err
    assert not list((work / "out").rglob("*.freepod"))


def test_a_symlink_inside_the_destination_cannot_carry_a_key_out(run, store, work, capsys):
    (work / "out").mkdir()
    (work / "outside").mkdir()
    (work / "out" / "link").symlink_to(work / "outside")
    store.put("link/x.txt", b"x")
    assert run(["cp", ":", str(work / "out")]) == EXIT_ERROR
    assert not (work / "outside" / "x.txt").exists()


def test_a_zero_length_folder_marker_becomes_a_folder(run, store, work):
    store.put("empty/", b"")
    store.put("full/f", b"x")
    assert run(["cp", ":", str(work / "out")]) == EXIT_OK
    assert (work / "out" / "empty").is_dir()


# ── large and interrupted transfers ─────────────────────────────────────────


def test_a_large_file_goes_up_in_parts(run, store, work, small_parts):
    data = os.urandom(5000)
    (work / "big.bin").write_bytes(data)
    assert run(["cp", str(work / "big.bin"), ":big.bin"]) == EXIT_OK
    assert store.objects["big.bin"] == data
    parts = [q for m, k, q in store.requests if m == "PUT" and "partNumber" in q]
    assert len(parts) == 5


def test_part_size_grows_only_past_ten_thousand_parts():
    assert objects._part_size(8 * objects.MIB) == objects.PART_SIZE
    assert objects._part_size(10_000 * 8 * objects.MIB) == objects.PART_SIZE
    grown = objects._part_size(10_000 * 8 * objects.MIB + 1)
    assert grown == 9 * objects.MIB


def test_a_failed_part_aborts_the_upload(run, store, work, small_parts, capsys):
    (work / "big.bin").write_bytes(os.urandom(5000))

    def fail_part_three(request, key, query):
        if query.get("partNumber") == "3":
            return httpx.Response(500)
        return None

    store.intercept = fail_part_three
    assert run(["cp", str(work / "big.bin"), ":big.bin"]) == EXIT_ERROR
    assert "big.bin" not in store.objects
    assert store.uploads == {}
    assert ("DELETE", "big.bin") in [(m, k) for m, k, q in store.requests if "uploadId" in q]
    assert "was not copied" in capsys.readouterr().err


def test_an_interrupted_upload_is_aborted(run, store, work, small_parts):
    (work / "big.bin").write_bytes(os.urandom(5000))

    def interrupt(request, key, query):
        if query.get("partNumber") == "2":
            raise KeyboardInterrupt
        return None

    store.intercept = interrupt
    assert run(["cp", str(work / "big.bin"), ":big.bin"]) == 130
    assert "big.bin" not in store.objects
    assert store.uploads == {}


def test_an_interrupted_download_leaves_nothing_behind(run, store, work):
    store.put("big.bin", b"x" * 4096)

    def body():
        yield b"x" * 1024
        raise KeyboardInterrupt

    def interrupt(request, key, query):
        if request.method == "GET" and key == "big.bin":
            return httpx.Response(200, stream=Stream(body()), headers={"content-length": "4096"})
        return None

    store.intercept = interrupt
    assert run(["cp", ":big.bin", str(work / "big.bin")]) == 130
    assert list(work.iterdir()) == []


def test_a_truncated_download_is_not_kept(run, store, work, capsys):
    store.put("f", b"full content")

    def short(request, key, query):
        if request.method == "GET" and key == "f":
            return httpx.Response(200, stream=Stream([b"full"]), headers={"content-length": "12", "etag": '"x"'})
        return None

    store.intercept = short
    # httpx itself refuses a body shorter than its Content-Length.
    assert run(["cp", ":f", str(work / "f")]) == EXIT_ERROR
    assert list(work.iterdir()) == []


def test_a_corrupted_download_is_not_kept(run, store, work, capsys):
    store.put("f", b"original")

    def corrupt(request, key, query):
        if request.method == "GET" and key == "f":
            return httpx.Response(
                200, stream=Stream([b"tampered"]), headers={"etag": f'"{hashlib.md5(b"original").hexdigest()}"'}
            )
        return None

    store.intercept = corrupt
    assert run(["cp", ":f", str(work / "f")]) == EXIT_ERROR
    assert list(work.iterdir()) == []
    assert "different content" in capsys.readouterr().err


# ── mv ──────────────────────────────────────────────────────────────────────


def test_mv_within_the_bucket(run, store):
    store.put("draft.txt", b"text")
    assert run(["mv", ":draft.txt", ":final.txt"]) == EXIT_OK
    assert store.objects == {"final.txt": b"text"}
    assert store.copies == [("draft.txt", "final.txt")]
    assert store.bodies == []


def test_mv_a_prefix_within_the_bucket(run, store):
    store.put("a/1", b"1")
    store.put("a/2/3", b"3")
    assert run(["mv", ":a", ":b"]) == EXIT_OK
    assert store.keys() == ["b/1", "b/2/3"]


def test_mv_up_removes_the_local_tree(run, store, work):
    (work / "exports" / "sub").mkdir(parents=True)
    (work / "exports" / "a.csv").write_text("a")
    (work / "exports" / "sub" / "b.csv").write_text("b")
    assert run(["mv", str(work / "exports"), ":exports"]) == EXIT_OK
    assert store.keys() == ["exports/a.csv", "exports/sub/b.csv"]
    assert not (work / "exports").exists()


def test_mv_down_removes_the_objects(run, store, work):
    store.put("exports/a.csv", b"a")
    store.put("exports/sub/b.csv", b"b")
    store.put("other", b"o")
    assert run(["mv", ":exports", str(work / "exports")]) == EXIT_OK
    assert (work / "exports" / "sub" / "b.csv").read_bytes() == b"b"
    assert store.keys() == ["other"]


def test_mv_keeps_the_source_of_a_failed_copy(run, store, capsys):
    store.put("a/1", b"1")
    store.put("a/2", b"2")

    def fail_one(request, key, query):
        if request.method == "PUT" and key == "b/2":
            return httpx.Response(500)
        return None

    store.intercept = fail_one
    assert run(["mv", ":a", ":b"]) == EXIT_ERROR
    assert store.keys() == ["a/2", "b/1"]
    err = capsys.readouterr().err
    assert "'a/2' was not moved" in err and "source was kept" in err


# ── rm ──────────────────────────────────────────────────────────────────────


def test_rm_an_object(run, store):
    store.put("a.txt", b"x")
    store.put("b.txt", b"x")
    assert run(["rm", ":a.txt"]) == EXIT_OK
    assert store.keys() == ["b.txt"]


def test_rm_a_prefix_needs_r_and_deletes_nothing_without_it(run, store, capsys):
    store.put("uploads/1", b"x")
    store.put("keep.txt", b"x")
    assert run(["rm", ":keep.txt", ":uploads"]) == EXIT_USAGE
    assert "-r" in capsys.readouterr().err
    assert store.keys() == ["keep.txt", "uploads/1"]


def test_rm_r_deletes_everything_under_the_prefix(run, store):
    for n in range(2500):
        store.put(f"uploads/{n}", b"x")
    store.put("keep.txt", b"x")
    assert run(["rm", "-r", "uploads"]) == EXIT_OK
    assert store.keys() == ["keep.txt"]
    batches = [m for m, k, q in store.requests if m == "POST" and "delete" in q]
    assert len(batches) == 3


def test_rm_of_nothing_fails(run, store, capsys):
    assert run(["rm", ":missing.txt"]) == EXIT_ERROR
    assert "no such object" in capsys.readouterr().err


def test_rm_never_touches_local_files(run, store, tmp_path):
    (tmp_path / "local.txt").write_text("mine")
    store.put("local.txt", b"theirs")
    assert run(["rm", "local.txt"]) == EXIT_OK
    assert (tmp_path / "local.txt").read_text() == "mine"
    assert store.keys() == []


# ── cat ─────────────────────────────────────────────────────────────────────


def test_cat_streams_bytes_unchanged(run, store, capsysbinary):
    data = bytes(range(256)) * 1000
    store.put("dump.bin", data)
    assert run(["cat", ":dump.bin"]) == EXIT_OK
    assert capsysbinary.readouterr().out == data


def test_cat_several_in_order(run, store, capsysbinary):
    store.put("a.txt", b"A")
    store.put("b.txt", b"B")
    assert run(["cat", ":b.txt", ":a.txt"]) == EXIT_OK
    assert capsysbinary.readouterr().out == b"BA"


def test_cat_refuses_a_prefix(run, store, capsys):
    store.put("uploads/1", b"x")
    assert run(["cat", ":uploads"]) == EXIT_ERROR
    assert "names a prefix" in capsys.readouterr().err


def test_cat_of_a_missing_object_fails(run, store, capsys):
    assert run(["cat", ":nope"]) == EXIT_ERROR
    assert "no such object" in capsys.readouterr().err


# ── link ────────────────────────────────────────────────────────────────────


def test_link_prints_only_a_presigned_get_url(run, store, capsys):
    store.put("report.pdf", b"%PDF")
    assert run(["link", ":report.pdf"]) == EXIT_OK
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    url = out.strip()
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    assert (parts.scheme, parts.netloc, parts.path) == ("https", "blob.example.test", f"/{BUCKET}/report.pdf")
    assert query["X-Amz-Expires"] == ["3600"] and "X-Amz-Signature" in query
    assert SECRET not in url


def test_link_put_needs_no_object(run, store, capsys):
    assert run(["link", "--put", "--expires", "30m", ":incoming/data.csv"]) == EXIT_OK
    assert "X-Amz-Expires=1800" in capsys.readouterr().out
    assert store.requests == []


@pytest.mark.parametrize("expires", ["8d", "604801s", "0", "soon"])
def test_link_refuses_a_bad_lifetime(run, store, capsys, expires):
    assert run(["link", "--expires", expires, ":x"]) == EXIT_USAGE
    assert capsys.readouterr().out == ""


def test_link_to_a_missing_object_is_refused(run, store, capsys):
    assert run(["link", ":nope.pdf"]) == EXIT_ERROR
    assert capsys.readouterr().out == ""


# ── failures and streams ────────────────────────────────────────────────────


def test_a_full_bucket_is_said_so(run, store, work, capsys):
    store.max_size = 10
    (work / "f.bin").write_bytes(b"x" * 100)
    assert run(["cp", str(work / "f.bin"), ":f.bin"]) == EXIT_ERROR
    assert "the bucket is full" in capsys.readouterr().err


def test_piped_output_is_only_the_result(run, store, capsys):
    store.put("a.txt", b"x")
    run(["ls"])
    assert capsys.readouterr().out == "a.txt\n"


def test_quiet_silences_success_but_not_a_skip(run, store, work, capsys):
    store.put("../escape", b"x")
    store.put("ok", b"x")
    assert run(["cp", ":", str(work / "out")], global_args=["--quiet"]) == EXIT_ERROR
    err = capsys.readouterr().err
    assert "'../escape' would land outside" in err
    assert "Copied" not in err


def test_without_quiet_a_copy_says_what_it_did(run, store, work, capsys):
    store.put("ok", b"x")
    assert run(["cp", ":", str(work / "out")]) == EXIT_OK
    assert "Copied 1 file" in capsys.readouterr().err


@pytest.mark.parametrize("command", [[], ["status"], ["ls"], ["cp"], ["mv"], ["rm"], ["cat"], ["link"]])
def test_help_works_on_the_group_and_every_command(command, capsys):
    assert main(["bucket", *command, "--help"]) == EXIT_OK
    assert "Usage:" in capsys.readouterr().out
