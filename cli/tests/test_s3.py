"""SigV4 signing and the small S3 client, without a store.

The signatures are AWS's own worked examples from the S3 documentation
("Signature Calculations for the Authorization Header" and "Authenticating
Requests: Using Query Parameters"), so a pass means the canonicalization is
S3's, not merely self-consistent.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import httpx
import pytest

from freepod import s3

AWS_CREDS = s3.Credentials(
    endpoint="https://examplebucket.s3.amazonaws.com",
    region="us-east-1",
    bucket="examplebucket",
    access_key_id="AKIAIOSFODNN7EXAMPLE",
    secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
)
AWS_TIME = datetime(2013, 5, 24, tzinfo=timezone.utc)


def _signature(headers: dict) -> str:
    return headers["authorization"].rsplit("Signature=", 1)[1]


def test_aws_example_get_object():
    headers = s3.sign_headers(
        AWS_CREDS,
        "GET",
        "https://examplebucket.s3.amazonaws.com/test.txt",
        [],
        {"Range": "bytes=0-9"},
        s3.EMPTY_SHA256,
        now=AWS_TIME,
    )
    assert "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date" in headers["authorization"]
    assert _signature(headers) == "f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"


def test_aws_example_put_object():
    body = b"Welcome to Amazon S3."
    headers = s3.sign_headers(
        AWS_CREDS,
        "PUT",
        "https://examplebucket.s3.amazonaws.com/test%24file.text",
        [],
        {"Date": "Fri, 24 May 2013 00:00:00 GMT", "x-amz-storage-class": "REDUCED_REDUNDANCY"},
        hashlib.sha256(body).hexdigest(),
        now=AWS_TIME,
    )
    assert _signature(headers) == "98ad721746da40c64f1a55b78f14c238d841ea1380cd77a1b5971af0ece108bd"


def test_aws_example_get_bucket_lifecycle():
    headers = s3.sign_headers(
        AWS_CREDS,
        "GET",
        "https://examplebucket.s3.amazonaws.com/",
        [("lifecycle", "")],
        {},
        s3.EMPTY_SHA256,
        now=AWS_TIME,
    )
    assert _signature(headers) == "fea454ca298b7da1c68078a5d1bdbfbbe0d65c699e0f91ac7a200a0136783543"


def test_aws_example_list_objects():
    headers = s3.sign_headers(
        AWS_CREDS,
        "GET",
        "https://examplebucket.s3.amazonaws.com/",
        [("max-keys", "2"), ("prefix", "J")],
        {},
        s3.EMPTY_SHA256,
        now=AWS_TIME,
    )
    assert _signature(headers) == "34b48302e7b5fa45bde8084f4b7868a86f0a534bc59db6670ed5711ef69dc6f7"


def test_aws_example_presigned_url():
    url = s3.presign(
        AWS_CREDS, "GET", "https://examplebucket.s3.amazonaws.com/test.txt", 86400, now=AWS_TIME
    )
    assert url.endswith(
        "X-Amz-Signature=aeeed9bbccd4d02ee5c0109b86d86835f995330da4c265957d157751f604d404"
    )
    assert "X-Amz-Expires=86400" in url


@pytest.mark.parametrize("expires", [0, s3.MAX_PRESIGN_SECONDS + 1])
def test_a_presign_outside_sigv4s_range_is_refused(expires):
    with pytest.raises(ValueError):
        s3.presign(AWS_CREDS, "GET", "https://examplebucket.s3.amazonaws.com/x", expires)


# ── Addressing ─────────────────────────────────────────────────────────────

CREDS = s3.Credentials("https://blob.example.test", "garage", "dep-1", "GKexample", "s3cr3t")


@pytest.mark.parametrize(
    "key, wire, canonical",
    [
        ("plain/key.txt", "/dep-1/plain/key.txt", "/dep-1/plain/key.txt"),
        ("sp ace+plus%pct.txt", "/dep-1/sp%20ace%2Bplus%25pct.txt", "/dep-1/sp%20ace%2Bplus%25pct.txt"),
        ("a//double.txt", "/dep-1/a//double.txt", "/dep-1/a//double.txt"),
        ("q?hash#.txt", "/dep-1/q%3Fhash%23.txt", "/dep-1/q%3Fhash%23.txt"),
        ("ü/文件", "/dep-1/%C3%BC/%E6%96%87%E4%BB%B6", "/dep-1/%C3%BC/%E6%96%87%E4%BB%B6"),
        ("~tilde-_.", "/dep-1/~tilde-_.", "/dep-1/~tilde-_."),
        # Dot segments are encoded on the wire, or the HTTP client would
        # resolve them away and send another key; the store signs them decoded.
        ("../../escape.txt", "/dep-1/%2E%2E/%2E%2E/escape.txt", "/dep-1/../../escape.txt"),
        ("./dot/f", "/dep-1/%2E/dot/f", "/dep-1/./dot/f"),
    ],
)
def test_keys_are_addressed_exactly(key, wire, canonical):
    bucket = s3.Bucket(CREDS, client=httpx.Client())
    url = bucket.url(key)
    assert url == "https://blob.example.test" + wire
    assert httpx.Client().build_request("GET", url).url.raw_path.decode() == wire
    assert bucket.canonical_path(key) == canonical


def test_credentials_never_show_the_secret_in_their_repr():
    assert "s3cr3t" not in repr(CREDS)


# ── The client over a stubbed transport ────────────────────────────────────


def _bucket(handler, **kwargs) -> s3.Bucket:
    return s3.Bucket(
        CREDS, client=httpx.Client(transport=httpx.MockTransport(handler)), retry_delay=0, **kwargs
    )


def _xml(body: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, content=body.encode(), headers={"content-type": "application/xml"})


def test_the_query_is_sent_exactly_as_signed():
    seen = []

    def handler(request):
        seen.append(request.url.raw_path.decode())
        return _xml(
            "<ListBucketResult><IsTruncated>false</IsTruncated></ListBucketResult>"
        )

    _bucket(handler).list_page("a b+c/", delimiter="/")
    assert seen == ["/dep-1?delimiter=%2F&list-type=2&prefix=a%20b%2Bc%2F"]


def test_listing_follows_continuation_tokens():
    pages = iter(
        [
            "<ListBucketResult><Contents><Key>a</Key><Size>1</Size></Contents>"
            "<IsTruncated>true</IsTruncated><NextContinuationToken>t+1</NextContinuationToken>"
            "</ListBucketResult>",
            "<ListBucketResult><Contents><Key>b</Key><Size>2</Size></Contents>"
            "<CommonPrefixes><Prefix>c/</Prefix></CommonPrefixes>"
            "<IsTruncated>false</IsTruncated></ListBucketResult>",
        ]
    )
    tokens = []

    def handler(request):
        tokens.append(request.url.params.get("continuation-token"))
        return _xml(next(pages))

    listings = list(_bucket(handler).walk(""))
    assert [o.key for page in listings for o in page.objects] == ["a", "b"]
    assert listings[1].prefixes == ["c/"]
    assert tokens == [None, "t+1"]


def test_a_failed_request_is_retried_once():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, headers={"etag": '"e"'})

    assert _bucket(handler).put("k", b"x") == "e"
    assert len(calls) == 2


def test_completion_is_never_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503)

    with pytest.raises(s3.S3Error):
        _bucket(handler).complete_multipart("k", "u", ["e1"])
    assert len(calls) == 1


def test_a_quota_refusal_says_the_bucket_is_full():
    garage = (
        "<Error><Code>AccessDenied</Code><Message>Forbidden: Bucket size quota is reached, "
        "maximum total size of objects for this bucket: 52428800. The bucket is already "
        "62914561 bytes, and this object would add 1048576 bytes.</Message></Error>"
    )
    with pytest.raises(s3.S3Error) as raised:
        _bucket(lambda r: _xml(garage, 403)).put("k", b"x")
    assert "the bucket is full" in str(raised.value)


def test_a_skewed_clock_is_named():
    garage = "<Error><Code>InvalidRequest</Code><Message>Bad request: Date is too old</Message></Error>"
    with pytest.raises(s3.S3Error) as raised:
        _bucket(lambda r: _xml(garage, 400)).put("k", b"x")
    assert "clock" in str(raised.value)


def test_a_missing_key_on_delete_many_is_not_a_failure():
    """Garage reports an already-absent key as an error; S3 counts it deleted."""
    body = (
        "<DeleteResult><Error><Key>gone</Key><Code>NoSuchKey</Code><Message>Key not found</Message></Error>"
        "<Error><Key>stuck</Key><Code>InternalError</Code><Message>boom</Message></Error></DeleteResult>"
    )
    assert _bucket(lambda r: _xml(body)).delete_many(["gone", "stuck"]) == [("stuck", "boom")]


def test_verbose_output_names_the_request_without_its_signature(capsys):
    def handler(request):
        assert "authorization" in request.headers
        return httpx.Response(200, headers={"etag": '"e"'})

    _bucket(handler, verbose=True).put("dir/file.txt", b"x")
    err = capsys.readouterr().err
    assert "PUT /dep-1/dir/file.txt" in err
    assert "s3cr3t" not in err
    assert "Signature" not in err and "Credential" not in err


def test_every_body_is_signed_with_its_hash():
    seen = {}

    def handler(request):
        seen.update(request.headers)
        return httpx.Response(200)

    _bucket(handler).put("k", b"payload")
    assert seen["x-amz-content-sha256"] == hashlib.sha256(b"payload").hexdigest()
