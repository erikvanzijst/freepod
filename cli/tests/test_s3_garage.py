"""The S3 client against a real Garage, the store `freepod bucket` talks to.

Starts a throwaway `dxflrs/garage` container (the version the platform runs) and
is skipped when Docker is not available. Inside a container — a devcontainer,
say — the store joins this container's network and is reached by name;
otherwise its port is published on localhost.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import socket
import subprocess
import threading
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from freepod import objects, s3

IMAGE = "dxflrs/garage:v2.3.0"
BUCKET = "dep-11111111-2222-3333-4444-555555555555"
SMALL_BUCKET = "dep-99999999-2222-3333-4444-555555555555"

CONFIG = """\
metadata_dir = "/var/lib/garage/meta"
data_dir = "/var/lib/garage/data"
db_engine = "sqlite"
replication_factor = 1
rpc_bind_addr = "[::]:3901"
rpc_public_addr = "127.0.0.1:3901"
rpc_secret = "{secret}"
[s3_api]
s3_region = "garage"
api_bind_addr = "[::]:3900"
"""


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check)


def _garage(name: str, *args: str) -> str:
    return _docker("exec", name, "/garage", *args).stdout


def _own_network() -> str:
    """This container's Docker network, or "" when not running in one."""
    result = _docker(
        "inspect", "-f", "{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}",
        socket.gethostname(), check=False,
    )
    return result.stdout.split()[0] if result.returncode == 0 and result.stdout.strip() else ""


def _pause(seconds: float) -> None:
    # Not time.sleep: the suite's autouse fixture makes that instantaneous.
    threading.Event().wait(seconds)


@pytest.fixture(scope="module")
def garage(tmp_path_factory):
    if shutil.which("docker") is None or _docker("info", check=False).returncode != 0:
        pytest.skip("Docker is not available")

    name = f"freepod-test-garage-{uuid.uuid4().hex[:8]}"
    network = _own_network()
    placement = ["--network", network] if network else ["-p", "127.0.0.1::3900"]
    config = tmp_path_factory.mktemp("garage") / "garage.toml"
    config.write_text(CONFIG.format(secret=os.urandom(32).hex()))

    _docker("create", "--name", name, *placement, IMAGE)
    try:
        _docker("cp", str(config), f"{name}:/etc/garage.toml")
        _docker("start", name)
        for _ in range(60):
            status = _docker("exec", name, "/garage", "status", check=False)
            if status.returncode == 0 and "127.0.0.1" in status.stdout:
                break
            _pause(0.5)
        node = re.search(r"^([0-9a-f]{16})\s", status.stdout, re.M).group(1)
        _garage(name, "layout", "assign", "-z", "dc1", "-c", "10G", node)
        _garage(name, "layout", "apply", "--version", "1")

        key = _garage(name, "key", "create", "app-test")
        key_id = re.search(r"Key ID:\s+(\S+)", key).group(1)
        secret = re.search(r"Secret key:\s+(\S+)", key).group(1)
        for bucket in (BUCKET, SMALL_BUCKET):
            _garage(name, "bucket", "create", bucket)
            _garage(name, "bucket", "allow", "--read", "--write", bucket, "--key", "app-test")
        _garage(name, "bucket", "set-quotas", SMALL_BUCKET, "--max-size", "1KiB")

        if network:
            endpoint = f"http://{name}:3900"
        else:
            port = _docker("port", name, "3900").stdout.strip().rsplit(":", 1)[1]
            endpoint = f"http://127.0.0.1:{port}"
        for _ in range(60):
            try:
                httpx.get(endpoint, timeout=2)
                break
            except httpx.HTTPError:
                _pause(0.5)

        yield s3.Credentials(endpoint, "garage", BUCKET, key_id, secret)
    finally:
        _docker("rm", "-f", name, check=False)


@pytest.fixture
def bucket(garage):
    with s3.Bucket(garage, retry_delay=0) as store:
        yield store
        for page in store.walk(""):
            store.delete_many([o.key for o in page.objects])


AWKWARD_KEYS = [
    "../../../../escape.txt",
    "foo/bar/../quux/file.txt",
    "./dot/file.txt",
    "a//double.txt",
    "sp ace+plus%pct.txt",
    "q?hash#.txt",
    "ünïcødé/文件.txt",
    "~tilde/x&y=z;.txt",
]


def test_awkward_keys_round_trip(bucket):
    for key in AWKWARD_KEYS:
        bucket.put(key, key.encode())
    listed = [o.key for page in bucket.walk("") for o in page.objects]
    assert sorted(listed) == sorted(AWKWARD_KEYS)
    for key in AWKWARD_KEYS:
        with bucket.download(key) as response:
            assert response.read() == key.encode()
        assert bucket.head(key).size == len(key.encode())


def test_listing_by_a_prefix_with_awkward_characters(bucket):
    bucket.put("sp ace+plus/x", b"x")
    bucket.put("sp ace other", b"x")
    page, _ = bucket.list_page("sp ace+plus/", delimiter="/")
    assert [o.key for o in page.objects] == ["sp ace+plus/x"]


def test_a_single_part_etag_is_the_md5(bucket):
    bucket.put("f", b"content")
    assert bucket.head("f").etag == hashlib.md5(b"content").hexdigest()


def test_multipart_round_trip_and_abort(bucket, tmp_path):
    data = os.urandom(objects.PART_SIZE + 3 * 1024 * 1024)
    path = tmp_path / "big.bin"
    path.write_bytes(data)
    pool = objects.Pool()
    try:
        objects.upload_file(bucket, path, "big.bin", pool, objects.Reporter(quiet=True))
    finally:
        pool.close()
    with bucket.download("big.bin") as response:
        assert response.read() == data
    assert bucket.head("big.bin").etag.endswith("-2")

    upload_id = bucket.create_multipart("aborted.bin")
    bucket.upload_part("aborted.bin", upload_id, 1, b"x" * (5 * 1024 * 1024))
    bucket.abort_multipart("aborted.bin", upload_id)
    assert bucket.head("aborted.bin") is None


def test_a_body_that_differs_from_its_signed_hash_is_refused(bucket, garage):
    url = bucket.url("tamper.txt")
    headers = s3.sign_headers(
        garage, "PUT", url, [], {}, hashlib.sha256(b"good").hexdigest(),
        canonical_path=bucket.canonical_path("tamper.txt"),
    )
    response = httpx.put(url, headers=headers, content=b"evil")
    assert response.status_code >= 400
    assert bucket.head("tamper.txt") is None


def test_server_side_copies(bucket):
    data = os.urandom(6 * 1024 * 1024)
    bucket.put("src.bin", data)
    bucket.copy("src.bin", "copy/../dst.bin")
    with bucket.download("copy/../dst.bin") as response:
        assert response.read() == data

    upload_id = bucket.create_multipart("parts.bin")
    first = bucket.upload_part_copy("parts.bin", upload_id, 1, "src.bin", 0, 5 * 1024 * 1024 - 1)
    second = bucket.upload_part_copy("parts.bin", upload_id, 2, "src.bin", 5 * 1024 * 1024, len(data) - 1)
    bucket.complete_multipart("parts.bin", upload_id, [first, second])
    with bucket.download("parts.bin") as response:
        assert response.read() == data


def test_delete_many(bucket):
    for key in ("a", "b&c", "d<e>"):
        bucket.put(key, b"x")
    assert bucket.delete_many(["a", "b&c", "d<e>", "never-existed"]) == []
    assert [o.key for page in bucket.walk("") for o in page.objects] == []


def test_presigned_urls_need_no_other_credentials(bucket):
    bucket.put("ünïcødé/report.pdf", b"%PDF")
    get = bucket.presign("GET", "ünïcødé/report.pdf", 60)
    assert httpx.get(get).content == b"%PDF"

    put = bucket.presign("PUT", "incoming/via link.csv", 60)
    assert httpx.put(put, content=b"a,b\n").status_code == 200
    assert bucket.head("incoming/via link.csv").size == 4


def test_a_skewed_clock_is_named(bucket, garage):
    url = bucket.url("")
    headers = s3.sign_headers(
        garage, "GET", url, [("list-type", "2")], {}, s3.EMPTY_SHA256,
        now=datetime.now(timezone.utc) - timedelta(days=2),
        canonical_path=bucket.canonical_path(""),
    )
    response = httpx.get(url + "?list-type=2", headers=headers)
    assert "clock" in str(s3._error(response, "listing"))


def test_a_full_bucket_is_said_so(garage):
    small = s3.Credentials(garage.endpoint, garage.region, SMALL_BUCKET, garage.access_key_id, garage.secret_access_key)
    with s3.Bucket(small, retry_delay=0) as store:
        with pytest.raises(s3.S3Error, match="the bucket is full"):
            store.put("big", b"x" * 4096)


def test_a_download_of_hostile_keys_stays_in_its_destination(bucket, tmp_path):
    for key in AWKWARD_KEYS:
        bucket.put(key, key.encode())
    out = tmp_path / "out"
    with pytest.raises(Exception, match="not copied"):
        objects.transfer(bucket, ":", str(out), move=False, reporter=objects.Reporter(quiet=True))
    written = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    assert written == sorted(
        [
            "a/double.txt",
            "dot/file.txt",
            "foo/quux/file.txt",
            "q?hash#.txt",
            "sp ace+plus%pct.txt",
            "~tilde/x&y=z;.txt",
            "ünïcødé/文件.txt",
        ]
    )
    assert not (tmp_path / "escape.txt").exists()
