"""The domain name an account is addressed under.

Every application a user deploys sits beneath one — `<app>.<subdomain>.<domain>`
— so a deploy needs two things from it: the suffix that completes a bare
hostname, and the fact that one is held at all. The platform refuses to create a
deployment without it (**400**, code `subdomain_required`), and that refusal
arrives at the very end of a deploy, after the archive has been packed, uploaded
and built. The client settles it in preflight instead, where the answer costs one
read rather than a spent build.

Deliberately not a claim. Choosing the name is a one-time, irreversible decision
whose comprehensibility rests on showing a whole address; a terminal cannot carry
that, so this module refuses and points at the browser. See design D8.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from . import FreepodError
from .api import ApiClient
from .config import Environment

SUBDOMAIN_PATH = "/api/me/subdomain"

#: The code the platform's create refuses with when no domain name is held.
#: Matched as a backstop for the race where one is somehow absent between
#: preflight and the create request.
DEPLOY_REFUSAL_CODE = "subdomain_required"


def read(api: ApiClient) -> Dict[str, Any]:
    """`GET /api/me/subdomain` — always 200, even when nothing is held."""
    return api.subdomain()


def held(record: Dict[str, Any]) -> Optional[str]:
    """The fully qualified name this account is addressed under, or None."""
    fqdn = record.get("fqdn")
    return fqdn if isinstance(fqdn, str) and fqdn else None


def explain(env: Environment) -> str:
    """Why the deploy cannot proceed, and what would fix it."""
    return (
        f"this account does not have a domain name yet.\n"
        f"  Every app you deploy is addressed underneath one. Choosing it is a\n"
        f"  one-time, permanent decision, so it is made in the browser:\n"
        f"  {env.api_base}\n"
        f"  Run this again once you have chosen. Nothing has been packed, built "
        f"or deployed."
    )


def require(api: ApiClient) -> str:
    """The account's domain name, or refuse the deploy before anything is spent."""
    fqdn = held(read(api))
    if fqdn is None:
        raise FreepodError(explain(api.env))
    return fqdn
