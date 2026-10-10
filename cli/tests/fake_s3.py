"""An in-memory S3 bucket behind an httpx transport, shaped like Garage.

Covers what `freepod bucket` sends: ListObjectsV2 with prefix, delimiter and
continuation; HEAD/GET/PUT; multipart (including UploadPartCopy); CopyObject;
DELETE and DeleteObjects. Like Garage, DeleteObjects reports a missing key as
an error, and a write past `max_size` is refused with Garage's quota text.

It does not verify signatures — the integration suite against a real Garage
does that — but it refuses any request that carries none.
"""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Callable, Dict, List, Optional
from urllib.parse import parse_qsl, unquote

import httpx

BUCKET = "dep-d8dtx4"
NS = "http://s3.amazonaws.com/doc/2006-03-01/"


def _xml(body: str, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        content=('<?xml version="1.0" encoding="UTF-8"?>' + body).encode(),
        headers={"content-type": "application/xml"},
    )


def _error(code: str, message: str, status: int) -> httpx.Response:
    return _xml(f"<Error><Code>{code}</Code><Message>{message}</Message></Error>", status)


def _esc(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Stream(httpx.SyncByteStream):
    """A body that is streamed rather than pre-read, as a real connection's is."""

    def __init__(self, chunks):
        self.chunks = chunks

    def __iter__(self):
        yield from self.chunks


class FakeS3:
    def __init__(self, *, page_size: int = 1000, max_size: Optional[int] = None):
        self.objects: Dict[str, bytes] = {}
        self.etags: Dict[str, str] = {}
        self.uploads: Dict[str, dict] = {}
        self.requests: List[tuple] = []
        #: (source, destination) of every server-side copy, and every body written.
        self.copies: List[tuple] = []
        self.bodies: List[bytes] = []
        self.page_size = page_size
        self.max_size = max_size
        #: Called with each request first; a response it returns is used instead.
        self.intercept: Optional[Callable[[httpx.Request, str, dict], Optional[httpx.Response]]] = None
        self._next_upload = 0

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))

    # -- helpers for tests ---------------------------------------------------

    def put(self, key: str, body: bytes) -> None:
        self.objects[key] = body
        self.etags[key] = hashlib.md5(body).hexdigest()

    def keys(self) -> List[str]:
        return sorted(self.objects)

    def methods(self) -> List[str]:
        return [method for method, _key, _query in self.requests]

    # -- the server ----------------------------------------------------------

    def handler(self, request: httpx.Request) -> httpx.Response:
        raw = request.url.raw_path.decode()
        path, _, query_string = raw.partition("?")
        query = dict(parse_qsl(query_string, keep_blank_values=True))
        segments = path.lstrip("/").split("/", 1)
        assert unquote(segments[0]) == BUCKET, f"wrong bucket in {raw}"
        key = unquote(segments[1]) if len(segments) > 1 else ""
        self.requests.append((request.method, key, query))

        if "authorization" not in request.headers:
            return _error("AccessDenied", "Forbidden: no signature", 403)
        if self.intercept is not None:
            response = self.intercept(request, key, query)
            if response is not None:
                return response

        method = request.method
        if method == "PUT" and request.content:
            self.bodies.append(request.content)
        if key == "":
            if method == "GET" and query.get("list-type") == "2":
                return self._list(query)
            if method == "POST" and "delete" in query:
                return self._delete_many(request.content)
            return _error("NotImplemented", f"{method} on the bucket", 501)
        if method == "HEAD":
            return self._head(key)
        if method == "GET":
            return self._get(key)
        if method == "PUT":
            if "x-amz-copy-source" in request.headers:
                return self._copy(request, key, query)
            if "partNumber" in query:
                return self._part(key, query, request.content)
            return self._put(key, request.content)
        if method == "POST" and "uploads" in query:
            self._next_upload += 1
            upload_id = f"upload-{self._next_upload}"
            self.uploads[upload_id] = {"key": key, "parts": {}}
            return _xml(f"<InitiateMultipartUploadResult><UploadId>{upload_id}</UploadId></InitiateMultipartUploadResult>")
        if method == "POST" and "uploadId" in query:
            return self._complete(key, query["uploadId"], request.content)
        if method == "DELETE" and "uploadId" in query:
            self.uploads.pop(query["uploadId"], None)
            return httpx.Response(204)
        if method == "DELETE":
            self.objects.pop(key, None)
            return httpx.Response(204)
        return _error("NotImplemented", method, 501)

    def _used(self) -> int:
        return sum(len(v) for v in self.objects.values())

    def _over_quota(self, adding: int) -> Optional[httpx.Response]:
        if self.max_size is not None and self._used() + adding > self.max_size:
            return _error(
                "AccessDenied",
                f"Forbidden: Bucket size quota is reached, maximum total size of objects "
                f"for this bucket: {self.max_size}. The bucket is already {self._used()} "
                f"bytes, and this object would add {adding} bytes.",
                403,
            )
        return None

    def _head(self, key: str) -> httpx.Response:
        if key not in self.objects:
            return httpx.Response(404)
        return httpx.Response(200, headers=self._headers(key))

    def _headers(self, key: str) -> dict:
        return {
            "content-length": str(len(self.objects[key])),
            "etag": f'"{self.etags[key]}"',
            "last-modified": format_datetime(datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc), usegmt=True),
        }

    def _get(self, key: str) -> httpx.Response:
        if key not in self.objects:
            return _error("NoSuchKey", "Key not found", 404)
        body = self.objects[key]
        chunks = [body[i:i + 4096] for i in range(0, len(body), 4096)]
        return httpx.Response(200, stream=Stream(chunks), headers=self._headers(key))

    def _put(self, key: str, body: bytes) -> httpx.Response:
        refused = self._over_quota(len(body))
        if refused is not None:
            return refused
        self.put(key, body)
        return httpx.Response(200, headers={"etag": f'"{self.etags[key]}"'})

    def _part(self, key: str, query: dict, body: bytes) -> httpx.Response:
        upload = self.uploads.get(query["uploadId"])
        if upload is None:
            return _error("NoSuchUpload", "Upload not found", 404)
        upload["parts"][int(query["partNumber"])] = body
        return httpx.Response(200, headers={"etag": f'"{hashlib.md5(body).hexdigest()}"'})

    def _copy(self, request: httpx.Request, key: str, query: dict) -> httpx.Response:
        source = unquote(request.headers["x-amz-copy-source"]).lstrip("/").split("/", 1)[1]
        self.copies.append((source, key))
        if source not in self.objects:
            return _error("NoSuchKey", "Key not found", 404)
        data = self.objects[source]
        if "partNumber" in query:
            first, last = request.headers["x-amz-copy-source-range"][len("bytes="):].split("-")
            part = data[int(first): int(last) + 1]
            self.uploads[query["uploadId"]]["parts"][int(query["partNumber"])] = part
            return _xml(f'<CopyPartResult><ETag>"{hashlib.md5(part).hexdigest()}"</ETag></CopyPartResult>')
        self.put(key, data)
        return _xml(f'<CopyObjectResult><ETag>"{self.etags[key]}"</ETag></CopyObjectResult>')

    def _complete(self, key: str, upload_id: str, body: bytes) -> httpx.Response:
        upload = self.uploads.pop(upload_id, None)
        if upload is None:
            return _error("NoSuchUpload", "Upload not found", 404)
        numbers = [int(e.text) for e in ET.fromstring(body).iter("PartNumber")]
        data = b"".join(upload["parts"][n] for n in numbers)
        refused = self._over_quota(len(data))
        if refused is not None:
            return refused
        self.objects[key] = data
        self.etags[key] = f"{hashlib.md5(data).hexdigest()}-{len(numbers)}"
        return _xml("<CompleteMultipartUploadResult><Key>k</Key></CompleteMultipartUploadResult>")

    def _delete_many(self, body: bytes) -> httpx.Response:
        errors = []
        for element in ET.fromstring(body).iter("Key"):
            key = element.text or ""
            if key in self.objects:
                del self.objects[key]
            else:
                errors.append(f"<Error><Key>{_esc(key)}</Key><Code>NoSuchKey</Code><Message>Key not found</Message></Error>")
        return _xml(f'<DeleteResult xmlns="{NS}">{"".join(errors)}</DeleteResult>')

    def _list(self, query: dict) -> httpx.Response:
        prefix = query.get("prefix", "")
        delimiter = query.get("delimiter") or None
        max_keys = min(int(query.get("max-keys", self.page_size)), self.page_size)
        after = query.get("continuation-token", "")

        entries = []  # (sort key, kind, value)
        seen_prefixes = set()
        for key in sorted(self.objects):
            if not key.startswith(prefix) or (after and key <= after):
                continue
            rest = key[len(prefix):]
            if delimiter and delimiter in rest:
                common = prefix + rest.split(delimiter, 1)[0] + delimiter
                if common in seen_prefixes or (after and common <= after):
                    continue
                seen_prefixes.add(common)
                entries.append((common, "prefix", common))
            else:
                entries.append((key, "object", key))

        page, more = entries[:max_keys], len(entries) > max_keys
        contents = "".join(
            f"<Contents><Key>{_esc(v)}</Key><Size>{len(self.objects[v])}</Size>"
            f"<LastModified>2026-10-10T12:00:00.000Z</LastModified>"
            f"<ETag>&quot;{self.etags[v]}&quot;</ETag></Contents>"
            for _s, kind, v in page
            if kind == "object"
        )
        prefixes = "".join(
            f"<CommonPrefixes><Prefix>{_esc(v)}</Prefix></CommonPrefixes>"
            for _s, kind, v in page
            if kind == "prefix"
        )
        token = f"<NextContinuationToken>{_esc(page[-1][0])}</NextContinuationToken>" if more else ""
        return _xml(
            f'<ListBucketResult xmlns="{NS}"><Name>{BUCKET}</Name><Prefix>{_esc(prefix)}</Prefix>'
            f"{contents}{prefixes}<IsTruncated>{'true' if more else 'false'}</IsTruncated>{token}"
            "</ListBucketResult>"
        )
