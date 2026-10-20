"""The handle an account's hostnames end in.

Every application a user deploys is addressed as `<app>-<handle>.<domain>`, so a
deploy needs two things from it: the suffix that shows what a bare hostname
becomes, and the fact that one is held at all. The platform refuses to create a
deployment without it (**400**, code `handle_required`), and that refusal
arrives at the very end of a deploy, after the archive has been packed, uploaded
and built. The client settles it in preflight instead, where the answer costs one
read rather than a spent build.

Deliberately not a claim. Choosing the name is a one-time, irreversible decision
whose comprehensibility rests on showing a whole address; a terminal cannot carry
that, so this module refuses and points at the browser.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from . import FreepodError
from .api import ApiClient
from .config import Environment

HANDLE_PATH = "/api/me/handle"

#: The code the platform's create refuses with when no handle is held.
#: Matched as a backstop for the race where one is somehow absent between
#: preflight and the create request.
DEPLOY_REFUSAL_CODE = "handle_required"


def read(api: ApiClient) -> Dict[str, Any]:
    """`GET /api/me/handle` — always 200, even when nothing is held."""
    return api.handle()


def suffix(record: Dict[str, Any]) -> Optional[str]:
    """The text that follows an application label in this account's
    hostnames, or None when no handle is held. Opaque: it is appended, never
    taken apart."""
    value = record.get("suffix")
    return value if isinstance(value, str) and value else None


def explain(env: Environment) -> str:
    """Why the deploy cannot proceed, and what would fix it."""
    return (
        f"this account does not have a handle yet.\n"
        f"  Every app you deploy gets a hostname ending in it. Choosing it is a\n"
        f"  one-time, permanent decision, so it is made in the browser:\n"
        f"  {env.api_base}\n"
        f"  Run this again once you have chosen. Nothing has been packed, built "
        f"or deployed."
    )


def require(api: ApiClient) -> str:
    """The account's hostname suffix, or refuse the deploy before anything is spent."""
    held = suffix(read(api))
    if held is None:
        raise FreepodError(explain(api.env))
    return held


def held_suffix(api: ApiClient) -> Optional[str]:
    """The account's hostname suffix, tolerating its absence or a failed read.

    Only used to show what a bare label becomes; nothing depends on it.
    """
    try:
        return suffix(read(api))
    except FreepodError:
        return None
