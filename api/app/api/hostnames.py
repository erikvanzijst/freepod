from __future__ import annotations

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel
from sqlmodel import Session

from app.config import get_settings
from app.db import get_session
from app.deps import get_current_user
from app.models import UserORM
from app.services.errors import HostnameException
from app.services.hostnames import (
    check_hostname_for_deployment,
    cname_target as platform_cname_target,
    complete_hostname,
    ownership_record,
)

router = APIRouter(tags=["hostnames"])


class OwnershipRecord(BaseModel):
    """The TXT record that proves the caller controls a proxied hostname's DNS."""

    name: str
    value: str


class HostnameCheck(BaseModel):
    """Result of validating a candidate hostname for a deployment.

    Fields:
    - ``fqdn``: the name that was checked: lowercased, and for a bare
      application label, completed beneath the caller's handle.
    - ``usable``: ``True`` when the name passed every validation check and can
      be used for a deployment; ``False`` otherwise.
    - ``reason``: ``None`` when ``usable`` is ``True``. When ``usable`` is
      ``False`` this is a short machine-readable code explaining the rejection,
      one of: ``invalid`` (malformed name, or not a tenant label of the form
      `<app>-<handle>`), ``reserved`` (reserved by the platform), ``claimed``
      (a tenant hostname ending in another account's handle), ``in_use``
      (already in use by another deployment), ``not_resolving`` (neither a
      CNAME to the platform domain, A/AAAA records on that domain's
      addresses, nor a Cloudflare-proxied record), or ``ownership_unverified``
      (proxied, but without the ownership record).
    - ``proxy``: ``cloudflare`` when the name's addresses are all
      Cloudflare's, whether or not it is usable; ``None`` otherwise. A usable
      proxied name is unverified: where Cloudflare forwards it cannot be seen.
    - ``ownership_record``: with ``proxy``, the TXT record that must exist
      for a proxied name to be usable; ``None`` without it.
    """

    fqdn: str
    usable: bool
    reason: str | None = None
    proxy: str | None = None
    ownership_record: OwnershipRecord | None = None


@router.get(
    "/hostnames/{value}",
    response_model=HostnameCheck,
    summary="Check whether a hostname is usable for a deployment",
    response_description=(
        "A HostnameCheck: the checked `fqdn`, a `usable` boolean, a "
        "machine-readable `reason` code when `usable` is false, and the "
        "`proxy` and `ownership_record` of a proxied name."
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
    value: str = Path(
        ...,
        description=(
            "A bare application label (`photos`), completed beneath the caller's "
            "handle, or a fully qualified name, checked as given. Lowercased "
            "before any checks run."
        ),
    ),
    current_user: UserORM = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> HostnameCheck:
    """Validate a candidate deployment hostname and report whether it can be
    used, without creating or reserving anything.

    ## Authorization
    Requires authentication. The answer depends on who is asking: whether
    `photos-alice.freepod.app` is usable is a different answer for the account
    holding `alice` than for any other.

    ## Parameters
    - `value` (path): a bare application label, completed to
      `<label>-<handle>.<tenant domain>` with the caller's handle, or a fully
      qualified name. The checked name is echoed back as `fqdn`.

    ## Behavior
    A name under the tenant domain must be one label of the form
    `<app>-<handle>`, ending in the caller's own handle. Any other name is a
    custom domain, which may not be under a platform domain and must point at
    the platform in DNS. Handle availability is not answered here; see the
    dry run of `POST /me/handle`.

    A custom domain whose addresses are all Cloudflare's is proxied through
    Cloudflare, and reported with `proxy=cloudflare` and the
    `ownership_record` it needs: a TXT record `_freepod.<fqdn>` whose value
    is `<handle>.<cname target>`. With that record it is usable, but
    unverified: the platform cannot see where Cloudflare forwards it.

    Checks stop at the first failure. On success the response is `usable=true`
    with `reason=null`. On failure it is `usable=false` with a machine-readable
    `reason` code; a rejected name is never returned as an error status:
    - `invalid` — malformed name, a tenant label not of the form
      `<app>-<handle>`, or a bare label from a caller holding no handle.
    - `reserved` — a `preview-` tenant label, or a name under a platform
      domain that is not a tenant hostname here.
    - `claimed` — a tenant hostname ending in another account's handle.
    - `in_use` — the hostname is already in use by another deployment.
    - `not_resolving` — a custom domain that neither has a CNAME record
      pointing at the platform domain (see `GET /cname-target`) nor A/AAAA
      records that are all among that domain's own addresses, the form a
      domain apex takes (including flattened CNAMEs and ALIAS records), nor
      is proxied through Cloudflare.
    - `ownership_unverified` — proxied through Cloudflare, without a TXT
      record at `ownership_record.name` holding `ownership_record.value`.

    ## Errors
    Always returns **200** for an authenticated caller. Rejected names are
    reported in the body via `usable=false` and a `reason` code; no 4xx status
    is returned for them.
    """
    fqdn = value.lower()
    try:
        fqdn = complete_hostname(fqdn, handle=current_user.handle)
        verdict = check_hostname_for_deployment(session, fqdn, handle=current_user.handle)
        return _check(fqdn, current_user, usable=True, proxy=verdict.proxy)
    except HostnameException as exc:
        return _check(fqdn, current_user, usable=False, reason=exc.reason, proxy=exc.proxy)


def _check(fqdn: str, user: UserORM, *, proxy: str | None, **fields) -> HostnameCheck:
    record = ownership_record(fqdn, handle=user.handle) if proxy else None
    return HostnameCheck(
        fqdn=fqdn,
        proxy=proxy,
        ownership_record=OwnershipRecord(name=record.name, value=record.value) if record else None,
        **fields,
    )


@router.get(
    "/cname-target",
    response_model=str,
    summary="Get the domain custom hostnames must CNAME to",
    response_description="The CNAME target domain as a JSON string (empty string when unconfigured).",
    responses={200: {"description": "The CNAME target, e.g. `\"dev.freepod.app\"`, or `\"\"` when no domain is configured."}},
)
def cname_target() -> str:
    """Return the domain that custom hostnames must point to: the tenant domain.

    To use your own domain with a deployment, create a CNAME record for it
    whose target is exactly this value, or, for a domain apex, A/AAAA records
    with the addresses this domain resolves to. The hostname check
    (`GET /hostnames/{fqdn}`) verifies that the records exist.

    ## Authorization
    Public — no authentication required.

    ## Behavior
    Returns the CNAME target domain. Returns an empty
    string when no platform domain is configured, in which case custom
    hostnames are not subject to the DNS check.

    ## Errors
    - Always **200**.
    """
    settings = get_settings()
    return platform_cname_target(settings) if settings.domain else ""
