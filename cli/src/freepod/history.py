"""The build history: reading a project's builds and rendering them.

A build belongs to a deployment, and a project records exactly one, so the
history is that deployment's builds. The one whose image the deployment is
running is marked.

That mark is why the deployment is read at all: without it the listing cannot
distinguish the build that is serving traffic from the four newer ones that
were built and never released.

The table is the command's **result** and goes to stdout; the legend and the
counts are diagnostics and go to stderr, so `freepod builds | ...` carries rows
and nothing else.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

from . import FreepodError
from .api import ApiClient
from .build import builds_path
from .table import (  # noqa: F401  (re-exported for callers of this module)
    BLANK,
    GAP,
    SHORT_DIGEST,
    abbreviate,
    elapsed,
    format_duration,
    format_time,
    parse_time,
    render,
)

#: How many builds a bare `freepod builds` shows. The endpoint has no
#: pagination and returns the lot, so this is a display bound, not a query one.
DEFAULT_LIMIT = 20

#: Marks the build whose image the project's deployment is currently running.
LIVE_MARKER = "*"

COLUMNS = ("", "BUILD", "STATUS", "CREATED", "DURATION", "IMAGE")


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------


def list_builds(api: ApiClient, user_id: int, deployment_id: str) -> List[Dict[str, Any]]:
    """The deployment's builds, most recent first — even once it is deleted.

    The order is the platform's, and is kept: re-sorting here would mean
    parsing every timestamp just to reproduce the answer already given, and
    would silently reorder rows the moment a timestamp failed to parse.
    """
    path = builds_path(user_id, deployment_id)
    body = api.get_json(path)
    if not isinstance(body, list):
        raise FreepodError(f"unexpected {path} response: {body!r}")
    return [entry for entry in body if isinstance(entry, dict)]


def deployed_image(api: ApiClient, user_id: int, deployment_id: str) -> Optional[str]:
    """The image the deployment runs, if there is one to read.

    A deleted deployment, one never applied, or one the platform cannot answer
    for yields None rather than a refusal: the mark is a convenience, and the
    listing is the result.
    """
    response = api.get(f"/api/users/{user_id}/deployments/{deployment_id}")
    if not response.is_success:
        return None

    values = response.json().get("user_values_json")
    image = values.get("image") if isinstance(values, dict) else None
    return image if isinstance(image, str) and image else None


def duration(build: Dict[str, Any], now: Optional[datetime] = None) -> Optional[timedelta]:
    """How long the build ran, or has been running."""
    return elapsed(build.get("started_at"), build.get("finished_at"), now)


def rows(
    builds: Sequence[Dict[str, Any]],
    *,
    live_image: Optional[str] = None,
    full_image: bool = False,
    now: Optional[datetime] = None,
) -> List[List[str]]:
    """One row per build, in the order given, headers first."""
    table = [list(COLUMNS)]
    for build in builds:
        image = build.get("image")
        live = bool(live_image) and image == live_image
        table.append(
            [
                LIVE_MARKER if live else "",
                str(build.get("id", BLANK)),
                str(build.get("status", BLANK)),
                format_time(build.get("created_at")),
                format_duration(duration(build, now)),
                abbreviate(image, full=full_image),
            ]
        )
    return table
