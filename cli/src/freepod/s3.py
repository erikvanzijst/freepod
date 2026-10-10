"""A small S3 client for one deployment's bucket on Freepod's object store.

Only what `freepod bucket` uses, path-style, against Garage: listing, single and
multipart uploads, streaming downloads, server-side copies, deletes, and
query-string presigning. Every request body is signed with its SHA-256, so the
store refuses a body that differs from what was read.

The credentials live in memory for one run. Nothing here writes them anywhere,
and verbose output names the request without its query string or headers.
"""

from __future__ import annotations

import hashlib
import hmac
import time
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterator, List, Optional, Sequence, Tuple
from urllib.parse import quote, urlsplit

import httpx

from . import FreepodError
from .auth import log
from .config import USER_AGENT

EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
UNSIGNED_PAYLOAD = "UNSIGNED-PAYLOAD"

#: SigV4's own ceiling for a query-string signature.
MAX_PRESIGN_SECONDS = 7 * 24 * 3600

#: S3's limit for a single CopyObject; above it a copy goes in parts.
MAX_COPY_OBJECT_BYTES = 5 * 1024 ** 3

#: Generous on reads, because a slow body is not a dead connection.
TIMEOUT = httpx.Timeout(60.0, connect=15.0)


@dataclass(frozen=True)
class Credentials:
    endpoint: str
    region: str
    bucket: str
    access_key_id: str
    secret_access_key: str = field(repr=False)


class S3Error(FreepodError):
    """A request the store refused, carrying its S3 error code."""

    def __init__(self, message: str, *, code: str = "", status: int = 0):
        super().__init__(message)
        self.code = code
        self.status = status


class NoSuchKey(S3Error):
    pass


# --------------------------------------------------------------------------
# Signing
# --------------------------------------------------------------------------


def _uri_encode(value: str, *, keep_slash: bool) -> str:
    return quote(value, safe="/-_.~" if keep_slash else "-_.~")


def _encode_key(key: str) -> str:
    """A key as a URL path, segment by segment.

    `.` and `..` segments are percent-encoded, because an HTTP client removes
    dot segments from a path and would send a different key — `a/../b` as
    `b` — than the one named.
    """
    return "/".join(
        "%2E" * len(segment) if segment in (".", "..") else _uri_encode(segment, keep_slash=False)
        for segment in key.split("/")
    )


def _canonical_query(params: Sequence[Tuple[str, str]]) -> str:
    encoded = sorted(
        (_uri_encode(k, keep_slash=False), _uri_encode(v, keep_slash=False)) for k, v in params
    )
    return "&".join(f"{k}={v}" for k, v in encoded)


def _signing_key(secret: str, date: str, region: str) -> bytes:
    key = ("AWS4" + secret).encode()
    for part in (date, region, "s3", "aws4_request"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    return key


def _string_to_sign(amz_date: str, scope: str, canonical_request: str) -> str:
    return "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ]
    )


def _canonical_request(
    method: str,
    path: str,
    query: Sequence[Tuple[str, str]],
    headers: Dict[str, str],
    payload_hash: str,
) -> Tuple[str, str]:
    names = sorted(headers)
    canonical_headers = "".join(f"{n}:{' '.join(headers[n].strip().split())}\n" for n in names)
    signed = ";".join(names)
    request = "\n".join(
        [method, path, _canonical_query(query), canonical_headers, signed, payload_hash]
    )
    return request, signed


def sign_headers(
    creds: Credentials,
    method: str,
    url: str,
    query: Sequence[Tuple[str, str]],
    headers: Dict[str, str],
    payload_hash: str,
    now: Optional[datetime] = None,
    canonical_path: Optional[str] = None,
) -> Dict[str, str]:
    """The headers that authenticate one request: `headers` plus SigV4's own.

    `url` carries the already-encoded path; `query` is passed separately so its
    canonical form and the sent form come from the same pairs. Every header
    given is signed, along with `host`, `x-amz-date` and
    `x-amz-content-sha256`.
    """
    now = now or datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date = amz_date[:8]
    parts = urlsplit(url)

    signed_headers = {k.lower(): v for k, v in headers.items()}
    signed_headers["host"] = parts.netloc
    signed_headers["x-amz-date"] = amz_date
    signed_headers["x-amz-content-sha256"] = payload_hash

    canonical, signed_names = _canonical_request(
        method, canonical_path or parts.path or "/", query, signed_headers, payload_hash
    )
    scope = f"{date}/{creds.region}/s3/aws4_request"
    signature = hmac.new(
        _signing_key(creds.secret_access_key, date, creds.region),
        _string_to_sign(amz_date, scope, canonical).encode(),
        hashlib.sha256,
    ).hexdigest()

    out = dict(signed_headers)
    out["authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={creds.access_key_id}/{scope}, "
        f"SignedHeaders={signed_names}, Signature={signature}"
    )
    return out


def presign(
    creds: Credentials,
    method: str,
    url: str,
    expires: int,
    now: Optional[datetime] = None,
    canonical_path: Optional[str] = None,
) -> str:
    """A URL that performs `method` on `url` with no other credentials."""
    if not 1 <= expires <= MAX_PRESIGN_SECONDS:
        raise ValueError("expiry out of range")
    now = now or datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date = amz_date[:8]
    parts = urlsplit(url)
    scope = f"{date}/{creds.region}/s3/aws4_request"
    query = [
        ("X-Amz-Algorithm", "AWS4-HMAC-SHA256"),
        ("X-Amz-Credential", f"{creds.access_key_id}/{scope}"),
        ("X-Amz-Date", amz_date),
        ("X-Amz-Expires", str(expires)),
        ("X-Amz-SignedHeaders", "host"),
    ]
    canonical, _ = _canonical_request(
        method, canonical_path or parts.path or "/", query, {"host": parts.netloc}, UNSIGNED_PAYLOAD
    )
    signature = hmac.new(
        _signing_key(creds.secret_access_key, date, creds.region),
        _string_to_sign(amz_date, scope, canonical).encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{url}?{_canonical_query(query)}&X-Amz-Signature={signature}"


# --------------------------------------------------------------------------
# Responses
# --------------------------------------------------------------------------


@dataclass
class ObjectInfo:
    key: str
    size: int
    last_modified: Optional[datetime] = None
    etag: str = ""


@dataclass
class Listing:
    objects: List[ObjectInfo]
    prefixes: List[str]


def _local(tag: str) -> str:
    """An element's name without its namespace, which S3 and Garage differ on."""
    return tag.rsplit("}", 1)[-1]


def _all(element: ET.Element, name: str) -> List[ET.Element]:
    return [child for child in element if _local(child.tag) == name]


def _text(element: Optional[ET.Element], name: str) -> str:
    if element is None:
        return ""
    children = _all(element, name)
    return (children[0].text or "") if children else ""


def _parse_time(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _http_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    from email.utils import parsedate_to_datetime

    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


def _error(response: httpx.Response, what: str) -> S3Error:
    """The refusal as the owner should read it."""
    code = message = ""
    if response.content:
        try:
            root = ET.fromstring(response.content)
            code, message = _text(root, "Code"), _text(root, "Message")
        except ET.ParseError:
            message = response.text.strip()[:300]
    lowered = message.lower()
    status = response.status_code

    if "quota" in lowered:
        return S3Error(
            f"the bucket is full, so {what} was refused.\n  {message}", code=code, status=status
        )
    # Garage answers a skewed clock with "Date is too old" (or in the future)
    # rather than S3's RequestTimeTooSkewed.
    if code == "RequestTimeTooSkewed" or "date is too" in lowered or "date is in the future" in lowered:
        return S3Error(
            "this machine's clock is too far from the object store's, so the request "
            "was refused. Set the clock correctly and try again.",
            code=code,
            status=status,
        )
    if code in ("NoSuchKey", "NoSuchUpload") or (status == 404 and not code):
        return NoSuchKey(f"{what}: no such object", code=code or "NoSuchKey", status=status)
    detail = f"{code}: {message}" if code or message else f"HTTP {status}"
    return S3Error(f"{what} failed — {detail}", code=code, status=status)


# --------------------------------------------------------------------------
# The client
# --------------------------------------------------------------------------


class Bucket:
    """One bucket, reached with one set of credentials."""

    def __init__(
        self,
        creds: Credentials,
        *,
        verbose: bool = False,
        client: Optional[httpx.Client] = None,
        retry_delay: float = 1.0,
    ):
        self.creds = creds
        self.verbose = verbose
        self.retry_delay = retry_delay
        self._client = client if client is not None else httpx.Client(timeout=TIMEOUT)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "Bucket":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # -- addressing -------------------------------------------------------

    def url(self, key: str = "") -> str:
        base = self.creds.endpoint.rstrip("/")
        path = "/" + _uri_encode(self.creds.bucket, keep_slash=False)
        if key:
            path += "/" + _encode_key(key)
        return base + path

    def canonical_path(self, key: str = "") -> str:
        """The path as the store canonicalizes it for a signature.

        It decodes the path it received and re-encodes it, so a `%2E%2E`
        segment sent on the wire is signed as `..`.
        """
        prefix = urlsplit(self.creds.endpoint).path.rstrip("/")
        path = prefix + "/" + _uri_encode(self.creds.bucket, keep_slash=False)
        if key:
            path += "/" + _uri_encode(key, keep_slash=True)
        return path

    def presign(self, method: str, key: str, expires: int) -> str:
        return presign(
            self.creds, method, self.url(key), expires, canonical_path=self.canonical_path(key)
        )

    # -- transport --------------------------------------------------------

    def _request(
        self,
        method: str,
        key: str = "",
        *,
        query: Sequence[Tuple[str, str]] = (),
        headers: Optional[Dict[str, str]] = None,
        body: bytes = b"",
        what: str = "",
        retry: bool = True,
        stream: bool = False,
        ok: Sequence[int] = (200, 204),
    ) -> httpx.Response:
        url = self.url(key)
        payload_hash = hashlib.sha256(body).hexdigest() if body else EMPTY_SHA256
        attempts = 2 if retry else 1
        what = what or f"{method} {key or '/'}"
        for attempt in range(1, attempts + 1):
            signed = sign_headers(
                self.creds,
                method,
                url,
                query,
                dict(headers or {}),
                payload_hash,
                canonical_path=self.canonical_path(key),
            )
            signed["user-agent"] = USER_AGENT
            if self.verbose:
                # The path only: the query and headers carry the signature.
                log(f"s3: {method} /{self.creds.bucket}/{key}")
            # The query goes on the URL in exactly its canonical form, so what is
            # sent is what was signed.
            request = self._client.build_request(
                method,
                f"{url}?{_canonical_query(query)}" if query else url,
                headers=signed,
                content=body if body else None,
            )
            try:
                response = self._client.send(request, stream=stream)
            except httpx.HTTPError as exc:
                if attempt < attempts:
                    time.sleep(self.retry_delay)
                    continue
                raise S3Error(f"{what} failed — cannot reach the object store: {exc.__class__.__name__}") from None
            if response.status_code >= 500 and attempt < attempts:
                response.close()
                time.sleep(self.retry_delay)
                continue
            if response.status_code not in ok:
                if stream:
                    response.read()
                    response.close()
                raise _error(response, what)
            return response
        raise AssertionError("unreachable")

    # -- reads ------------------------------------------------------------

    def head(self, key: str) -> Optional[ObjectInfo]:
        try:
            response = self._request("HEAD", key, what=f"reading '{key}'")
        except S3Error as exc:
            if exc.status == 404:
                return None
            raise
        return ObjectInfo(
            key=key,
            size=int(response.headers.get("content-length", "0")),
            last_modified=_http_time(response.headers.get("last-modified")),
            etag=response.headers.get("etag", "").strip('"'),
        )

    def list_page(
        self,
        prefix: str,
        *,
        delimiter: Optional[str] = None,
        token: Optional[str] = None,
        max_keys: Optional[int] = None,
    ) -> Tuple[Listing, Optional[str]]:
        query: List[Tuple[str, str]] = [("list-type", "2"), ("prefix", prefix)]
        if delimiter:
            query.append(("delimiter", delimiter))
        if token:
            query.append(("continuation-token", token))
        if max_keys:
            query.append(("max-keys", str(max_keys)))
        response = self._request("GET", query=query, what=f"listing '{prefix or '/'}'")
        root = ET.fromstring(response.content)
        objects = [
            ObjectInfo(
                key=_text(item, "Key"),
                size=int(_text(item, "Size") or 0),
                last_modified=_parse_time(_text(item, "LastModified")),
                etag=_text(item, "ETag").strip('"'),
            )
            for item in _all(root, "Contents")
        ]
        prefixes = [_text(item, "Prefix") for item in _all(root, "CommonPrefixes")]
        truncated = _text(root, "IsTruncated") == "true"
        next_token = _text(root, "NextContinuationToken") if truncated else None
        return Listing(objects, prefixes), next_token or None

    def walk(self, prefix: str, *, delimiter: Optional[str] = None) -> Iterator[Listing]:
        """Every page under `prefix`, as the store returns them."""
        token: Optional[str] = None
        while True:
            page, token = self.list_page(prefix, delimiter=delimiter, token=token)
            yield page
            if token is None:
                return

    def has_prefix(self, prefix: str) -> bool:
        page, _ = self.list_page(prefix, max_keys=1)
        return bool(page.objects)

    @contextmanager
    def download(self, key: str) -> Iterator[httpx.Response]:
        response = self._request("GET", key, stream=True, what=f"reading '{key}'")
        try:
            yield response
        finally:
            response.close()

    # -- writes -----------------------------------------------------------

    def put(self, key: str, body: bytes) -> str:
        response = self._request("PUT", key, body=body, what=f"writing '{key}'")
        return response.headers.get("etag", "").strip('"')

    def create_multipart(self, key: str) -> str:
        response = self._request(
            "POST", key, query=[("uploads", "")], what=f"starting '{key}'", retry=False
        )
        upload_id = _text(ET.fromstring(response.content), "UploadId")
        if not upload_id:
            raise S3Error(f"starting '{key}' failed — the store returned no upload id")
        return upload_id

    def upload_part(self, key: str, upload_id: str, number: int, body: bytes) -> str:
        response = self._request(
            "PUT",
            key,
            query=[("partNumber", str(number)), ("uploadId", upload_id)],
            body=body,
            what=f"writing part {number} of '{key}'",
        )
        return response.headers.get("etag", "")

    def upload_part_copy(
        self, key: str, upload_id: str, number: int, source: str, first: int, last: int
    ) -> str:
        response = self._request(
            "PUT",
            key,
            query=[("partNumber", str(number)), ("uploadId", upload_id)],
            headers={
                "x-amz-copy-source": self._copy_source(source),
                "x-amz-copy-source-range": f"bytes={first}-{last}",
            },
            what=f"copying part {number} of '{source}'",
        )
        root = ET.fromstring(response.content)
        return _text(root, "ETag")

    def complete_multipart(self, key: str, upload_id: str, etags: Sequence[str]) -> None:
        parts = "".join(
            f"<Part><PartNumber>{n}</PartNumber><ETag>{etag}</ETag></Part>"
            for n, etag in enumerate(etags, start=1)
        )
        body = f"<CompleteMultipartUpload>{parts}</CompleteMultipartUpload>".encode()
        response = self._request(
            "POST",
            key,
            query=[("uploadId", upload_id)],
            body=body,
            what=f"completing '{key}'",
            retry=False,
        )
        # S3 may report a failed completion inside a 200.
        if b"<Error>" in response.content:
            raise _error(
                httpx.Response(500, content=response.content), f"completing '{key}'"
            )

    def abort_multipart(self, key: str, upload_id: str) -> None:
        self._request(
            "DELETE",
            key,
            query=[("uploadId", upload_id)],
            what=f"aborting '{key}'",
            ok=(200, 204, 404),
        )

    def _copy_source(self, key: str) -> str:
        return "/" + _uri_encode(self.creds.bucket, keep_slash=False) + "/" + _encode_key(key)

    def copy(self, source: str, destination: str) -> None:
        response = self._request(
            "PUT",
            destination,
            headers={"x-amz-copy-source": self._copy_source(source)},
            what=f"copying '{source}' to '{destination}'",
        )
        if b"<Error>" in response.content:
            raise _error(
                httpx.Response(500, content=response.content),
                f"copying '{source}' to '{destination}'",
            )

    def delete(self, key: str) -> None:
        self._request("DELETE", key, what=f"deleting '{key}'")

    def delete_many(self, keys: Sequence[str]) -> List[Tuple[str, str]]:
        """Delete up to 1000 keys in one request; the ones that failed, with why."""
        if not keys:
            return []
        objects = "".join(f"<Object><Key>{_xml_escape(k)}</Key></Object>" for k in keys)
        body = f"<Delete><Quiet>true</Quiet>{objects}</Delete>".encode()
        response = self._request(
            "POST",
            query=[("delete", "")],
            headers={"content-md5": _md5_b64(body)},
            body=body,
            what="deleting objects",
        )
        root = ET.fromstring(response.content)
        # Garage reports a key that was already gone as an error, where S3
        # counts it deleted; either way it no longer exists.
        return [
            (_text(e, "Key"), _text(e, "Message") or _text(e, "Code"))
            for e in _all(root, "Error")
            if _text(e, "Code") != "NoSuchKey" and _text(e, "Message") != "Key not found"
        ]


def _xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _md5_b64(body: bytes) -> str:
    import base64

    return base64.b64encode(hashlib.md5(body).digest()).decode()

