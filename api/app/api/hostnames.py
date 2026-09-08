from __future__ import annotations

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel
from sqlmodel import Session

from app.config import get_settings
from app.db import get_session
from app.deps import get_current_user
from app.models import UserORM
from app.services.errors import HostnameException
from app.services.hostnames import check_hostname_availability

router = APIRouter(tags=["hostnames"])


class HostnameCheck(BaseModel):
    """Result of validating a candidate hostname for a deployment.

    Fields:
    - ``fqdn``: the fully-qualified domain name that was checked, normalized to
      lowercase (echoed back so the caller sees the canonical form).
    - ``usable``: ``True`` when the name passed every validation check and can
      be used for a deployment; ``False`` otherwise.
    - ``reason``: ``None`` when ``usable`` is ``True``. When ``usable`` is
      ``False`` this is a short machine-readable code explaining the rejection,
      one of: ``invalid`` (malformed name, or the wrong number of labels under
      a platform wildcard domain), ``reserved`` (reserved by the platform),
      ``claimed`` (a subdomain another account holds, or an application under
      one), ``in_use`` (already in use by another deployment), or
      ``not_resolving`` (no CNAME record pointing at the platform CNAME target).
    """

    fqdn: str
    usable: bool
    reason: str | None = None


@router.get(
    "/hostnames/{fqdn}",
    response_model=HostnameCheck,
    summary="Check whether a hostname is usable for a deployment",
    response_description=(
        "A HostnameCheck: the normalized `fqdn`, a `usable` boolean, and a "
        "human-readable `reason` code when `usable` is false."
    ),
    responses={
        200: {
            "description": (
                "Always 200. `usable=true` with `reason=null` for accepted "
                "names; `usable=false` with a `reason` code for rejected names. "
                "Rejections are never surfaced as an error status."
            )
        }
    },
)
def check_hostname(
    fqdn: str = Path(
        ...,
        description=(
            "Fully-qualified domain name to validate. Lowercased server-side "
            "before any checks run and echoed back normalized in the response."
        ),
    ),
    current_user: UserORM = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> HostnameCheck:
    """Validate a candidate hostname and report whether it can be used for a
    deployment, without creating or reserving anything.

    ## Authorization
    Requires authentication. The answer depends on who is asking: whether
    `photos.alice.freepod.eu` is usable is a different answer for the account
    holding `alice` than for any other.

    ## Parameters
    - `fqdn` (path): the hostname to validate. Normalized to lowercase; the
      normalized form is echoed back in the response.

    ## Behavior
    Which question is asked depends on the name's depth under a platform
    wildcard domain. A **single label** (`alice.freepod.eu`) asks whether that
    account subdomain can be claimed; **two labels**
    (`photos.alice.freepod.eu`) ask whether that application name is usable
    beneath the caller's own subdomain. A name outside every wildcard domain is
    a custom deployment hostname and is answered as one.

    Checks stop at the first failure. On success the response is `usable=true`
    with `reason=null`. On failure it is `usable=false` with a machine-readable
    `reason` code; a rejected name is never returned as an error status:
    - `invalid` — malformed name, or the wrong number of labels under a platform
      wildcard domain.
    - `reserved` — the name is reserved by the platform.
    - `claimed` — a subdomain another account holds, or an application name
      placed under somebody else's subdomain.
    - `in_use` — the hostname is already in use by another deployment.
    - `not_resolving` — the hostname has no CNAME record pointing at the
      platform CNAME target (see `GET /cname-target`). Not applicable to a name
      under a platform wildcard domain, or when no platform domain is
      configured.

    ## Errors
    Always returns **200** for an authenticated caller. Rejected names are
    reported in the body via `usable=false` and a `reason` code; no 4xx status
    is returned for them.
    """
    fqdn = fqdn.lower()
    try:
        check_hostname_availability(session, fqdn, subdomain=current_user.subdomain)
        return HostnameCheck(fqdn=fqdn, usable=True)
    except HostnameException as exc:
        return HostnameCheck(fqdn=fqdn, usable=False, reason=exc.reason)


@router.get(
    "/cname-target",
    response_model=str,
    summary="Get the platform domain custom hostnames must CNAME to",
    response_description="The platform CNAME target domain as a JSON string (empty string when unconfigured).",
    responses={200: {"description": "The CNAME target, e.g. `\"dev.freepod.eu\"`, or `\"\"` when no domain is configured."}},
)
def cname_target() -> str:
    """Return the platform domain that custom hostnames must point to.

    To use your own domain with a deployment, create a CNAME record for it
    whose target is exactly this value. The hostname check
    (`GET /hostnames/{fqdn}`) verifies that this record exists.

    ## Authorization
    Public — no authentication required.

    ## Behavior
    Returns the CNAME target domain. Returns an
    empty string when no platform domain is configured, in which case custom
    hostnames are not subject to the CNAME check.

    ## Errors
    - Always **200**.
    """
    return get_settings().domain
