"""What a project file sends to its deployment, and the caller's deployment names.

`init`, `apply` and `deploy` all send the file's keys the same way: `name`,
`description` and `icon` as the deployment's identity, every other key as a
chart value, and the file's keys as `managed_fields` (design D3).
"""

from __future__ import annotations

import base64
from typing import Any, Dict, List, Optional

from . import FreepodError
from .api import ApiClient
from .project import Project

#: The largest icon the platform accepts, before base64.
ICON_MAX_BYTES = 256 * 1024

#: Statuses whose deployment no longer holds its name.
_RELEASED_NAME = frozenset({"deleted"})


def encode_icon(project: Project) -> Optional[str]:
    """The file's icon as base64, None for a null `icon`.

    Refused before anything is sent when the path is missing, leaves the
    project, or names a file over the limit.
    """
    path = project.fields.get("icon")
    if path is None:
        return None
    if not isinstance(path, str) or not path.strip():
        raise FreepodError("'icon' must be a path to an image file, relative to the project root")
    target = (project.root / path).resolve()
    try:
        target.relative_to(project.root.resolve())
    except ValueError:
        raise FreepodError(f"icon {path} is outside the project directory") from None
    if not target.is_file():
        raise FreepodError(f"icon {path} does not exist in {project.root}")
    size = target.stat().st_size
    if size > ICON_MAX_BYTES:
        raise FreepodError(
            f"icon {path} is {size // 1024} KiB; the limit is {ICON_MAX_BYTES // 1024} KiB"
        )
    return base64.b64encode(target.read_bytes()).decode("ascii")


def identity_payload(project: Project) -> Dict[str, Any]:
    """The identity keys the file sets, as the platform takes them."""
    payload: Dict[str, Any] = {}
    for key in ("name", "description"):
        if key in project.fields:
            payload[key] = project.fields[key]
    if "icon" in project.fields:
        payload["icon"] = encode_icon(project)
    return payload


def claimed_body(project: Project) -> Dict[str, Any]:
    """The identity and `managed_fields` a request carries to claim the file's keys."""
    return {**identity_payload(project), "managed_fields": project.managed_fields}


def list_deployments(api: ApiClient, user_id: int) -> List[Dict[str, Any]]:
    """The caller's deployments on this environment, deleted ones left out."""
    records = api.get_json(f"/api/users/{user_id}/deployments")
    if not isinstance(records, list):
        return []
    return [r for r in records if isinstance(r, dict) and r.get("status") not in _RELEASED_NAME]


def named(deployments: List[Dict[str, Any]], name: str) -> Optional[Dict[str, Any]]:
    """The deployment holding `name`, compared as the platform does, ignoring case."""
    wanted = name.strip().lower()
    for record in deployments:
        if str(record.get("name") or "").strip().lower() == wanted:
            return record
    return None


def first_free_name(deployments: List[Dict[str, Any]], base: str) -> str:
    """`base`, or the first of `base 2`, `base 3`… that no deployment holds."""
    if named(deployments, base) is None:
        return base
    number = 2
    while named(deployments, f"{base} {number}") is not None:
        number += 1
    return f"{base} {number}"
