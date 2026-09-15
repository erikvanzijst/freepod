"""The bucket keeps each product's files; signed links serve them (D6)."""

from __future__ import annotations

import os

CONTENT_TYPES = {
    "session.jsonl": "application/x-ndjson; charset=utf-8",
    "session.html": "text/html; charset=utf-8",
    "stdout.txt": "text/plain; charset=utf-8",
    "result.json": "application/json",
    "body.md": "text/plain; charset=utf-8",
    "change.patch": "text/plain; charset=utf-8",
}
LINK_SECONDS = 3600


def product_prefix(run_id: int, slug: str) -> str:
    return f"runs/{run_id}/{slug}/"


class S3Store:
    def __init__(self, bucket: str | None = None, client=None):
        import boto3
        from botocore.config import Config

        self.bucket = bucket or os.environ.get("S3_BUCKET") or os.environ["BUCKET_NAME"]
        self.client = client or boto3.client("s3", config=Config(s3={"addressing_style": "path"}))

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def url(self, key: str) -> str:
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=LINK_SECONDS
        )
