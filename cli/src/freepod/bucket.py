"""`freepod bucket`: the deployment's object storage bucket.

The platform hands the owner the same bucket, endpoint and access key the pod
receives, and the commands talk to the bucket directly over its public S3
endpoint. The credentials are fetched on every run and held in memory only:
caching a live read/write key on disk would buy one request per command.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from . import FreepodError
from .api import ApiClient
from .database import MASK, format_bytes, format_usage
from .s3 import Credentials
from .table import render

NO_BUCKET_CODE = "object_storage_unavailable"

REVEAL_HINT = "(--show-secret to reveal)"


def _path(user_id: int, deployment_id: str) -> str:
    return f"/api/users/{user_id}/deployments/{deployment_id}/bucket"


def read(
    api: ApiClient, user_id: int, deployment_id: str, *, usage: bool = True
) -> Optional[Dict[str, Any]]:
    """The deployment's bucket details, or None when it has none.

    None is an answer, not a failure: a product without object storage is a
    normal state, and carries the platform's stable code. A 404 without it is a
    missing deployment and stays an error.
    """
    params = None if usage else {"usage": "false"}
    response = api.get(_path(user_id, deployment_id), params=params)
    if response.status_code == 404:
        try:
            body = response.json()
        except ValueError:
            body = {}
        if isinstance(body, dict) and body.get("code") == NO_BUCKET_CODE:
            return None
        detail = body.get("detail") if isinstance(body, dict) else None
        raise FreepodError(detail or "no such deployment")

    if not response.is_success:
        raise FreepodError(
            f"HTTP {response.status_code} from {response.url}: "
            f"{response.text.strip()[:300]}"
        )
    body = response.json()
    if not isinstance(body, dict):
        raise FreepodError(f"unexpected bucket response: {body!r}")
    return body


def credentials(details: Optional[Dict[str, Any]]) -> Credentials:
    """The credentials an object command uses, or the refusal that explains why not."""
    if details is None:
        raise FreepodError("this deployment has no bucket — its product does not offer object storage.")
    secret = details.get("secret_access_key")
    if not secret:
        raise FreepodError(
            "the bucket's contents are reachable by the deployment's owner alone; "
            "the platform withheld its secret from you."
        )
    return Credentials(
        endpoint=details["endpoint"],
        region=details["region"],
        bucket=details["bucket"],
        access_key_id=details["access_key_id"],
        secret_access_key=secret,
    )


def render_status(details: Dict[str, Any], *, show_secret: bool) -> str:
    """The command's result: identity, credentials and usage, as a table."""
    secret = details.get("secret_access_key")
    if secret is None:
        shown = "withheld — only the owner can read it"
    elif show_secret:
        shown = secret
    else:
        shown = f"{MASK} {REVEAL_HINT}"

    usage = details.get("usage") or {}
    rows = [
        ("Bucket", str(details.get("bucket", ""))),
        ("Endpoint", str(details.get("endpoint", ""))),
        ("Region", str(details.get("region", ""))),
        ("Access key", str(details.get("access_key_id", ""))),
        ("Secret key", shown),
        ("Size", _size(usage)),
        ("Objects", _objects(usage)),
    ]
    return render(rows)


def _size(usage: Dict[str, Any]) -> str:
    size = usage.get("bytes")
    if not isinstance(size, int):
        return "not reported"
    limit = usage.get("max_size_bytes")
    if not isinstance(limit, int):
        return format_bytes(size)
    return format_usage(size, limit)


def _objects(usage: Dict[str, Any]) -> str:
    count = usage.get("objects")
    if not isinstance(count, int):
        return "not reported"
    limit = usage.get("max_objects")
    if not isinstance(limit, int):
        return f"{count:,}"
    return f"{count:,} of {limit:,}"
