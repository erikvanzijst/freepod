from __future__ import annotations

import ipaddress
import logging
import re
from uuid import UUID

import dns.exception
import dns.resolver
from sqlmodel import Session, select

from app.config import CaelusSettings, get_settings
from app.models import DeploymentORM
from app.services.errors import HostnameException
from app.services.reconcile_constants import DEPLOYMENT_STATUS_DELETED

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

logger = logging.getLogger(__name__)

# RFC 952/1123: labels are 1-63 chars, alphanumeric + hyphens, no leading/trailing hyphens.
# Total FQDN max 253 chars.
_LABEL_RE = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$")

# A tenant hostname is one label beneath the tenant domain, `<app>-<handle>`.
# A handle has no `-`, so it is the text after the label's last one; the
# application part is 1-34 characters, which with the reserved `preview-`
# prefix (8) and a 20-character handle is the 63-character label limit.
APP_LABEL_MAX_LENGTH = 34
_APP_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
HANDLE_MIN_LENGTH = 2
HANDLE_MAX_LENGTH = 20
HANDLE_RE = re.compile(rf"^[a-z0-9]{{{HANDLE_MIN_LENGTH},{HANDLE_MAX_LENGTH}}}$")

# `preview-<app>-<handle>` names the live preview of the application at
# `<app>-<handle>`, so no deployment may claim one.
PREVIEW_LABEL_PREFIX = "preview-"


def _check_format(fqdn: str) -> None:
    if not fqdn or len(fqdn) > 253:
        raise HostnameException("invalid")
    labels = fqdn.rstrip(".").split(".")
    if len(labels) < 2:
        raise HostnameException("invalid")
    for label in labels:
        if not label or not _LABEL_RE.match(label):
            raise HostnameException("invalid")


def _under(fqdn: str, domain: str) -> bool:
    return bool(domain) and (fqdn == domain or fqdn.endswith(f".{domain}"))


def complete_hostname(
    value: str, *, handle: str | None, settings: CaelusSettings | None = None
) -> str:
    """Lowercase *value* and, when it is a bare application label (no dot),
    complete it beneath *handle* as `<label>-<handle>.<tenant domain>`.

    A bare label for an owner holding no handle has nothing to complete to and
    is refused as invalid.
    """
    value = value.lower()
    if "." in value:
        return value
    if not handle:
        raise HostnameException("invalid")
    settings = settings or get_settings()
    return f"{value}-{handle}.{settings.tenant_domain}"


def _check_tenant_label(fqdn: str, *, handle: str | None, settings: CaelusSettings) -> None:
    label = fqdn[: -(len(settings.tenant_domain) + 1)] if fqdn != settings.tenant_domain else ""
    if not label or "." in label or "-" not in label:
        raise HostnameException("invalid")
    app, _, owner = label.rpartition("-")
    if (
        not HANDLE_RE.match(owner)
        or len(app) > APP_LABEL_MAX_LENGTH
        or not _APP_LABEL_RE.match(app)
        or "--" in app
    ):
        raise HostnameException("invalid")
    if owner != (handle or "").lower():
        raise HostnameException("claimed")
    if app.startswith(PREVIEW_LABEL_PREFIX):
        raise HostnameException("reserved")


def _check_available(session: Session, fqdn: str, *, exclude_deployment_id: UUID | None = None) -> None:
    stmt = select(DeploymentORM.id).where(
        DeploymentORM.hostname == fqdn,
        DeploymentORM.status != DEPLOYMENT_STATUS_DELETED,
    )
    if exclude_deployment_id is not None:
        stmt = stmt.where(DeploymentORM.id != exclude_deployment_id)
    if session.exec(stmt).first() is not None:
        raise HostnameException("in_use")


def _authoritative_resolver(fqdn: str) -> dns.resolver.Resolver | None:
    """Build a resolver that queries the authoritative nameservers for *fqdn*
    directly, bypassing any recursive resolver's cache — including the negative
    cache that would otherwise pin a "no such record" answer for the zone's SOA
    negative TTL after a failed check.

    Returns ``None`` when the authoritative servers can't be determined (so the
    caller can fall back to the default system resolver).
    """
    try:
        zone = dns.resolver.zone_for_name(fqdn)
        ns_records = dns.resolver.resolve(zone, "NS")
    except dns.exception.DNSException:
        return None

    nameserver_ips: list[str] = []
    for ns in ns_records:
        for record_type in ("A", "AAAA"):
            try:
                nameserver_ips.extend(r.address for r in dns.resolver.resolve(ns.target, record_type))
            except dns.exception.DNSException:
                continue

    if not nameserver_ips:
        return None

    resolver = dns.resolver.Resolver(configure=False)
    resolver.nameservers = nameserver_ips
    # Keep the UI responsive: the user is waiting on this check.
    resolver.timeout = 3
    resolver.lifetime = 5
    return resolver


def _lookup(fqdn: str, rdtype: str, resolver: dns.resolver.Resolver | None) -> list:
    """The *rdtype* records at *fqdn*, empty when the answer is definitively
    that there are none.

    Asks *resolver* (the authoritative servers) and falls back to the system
    resolver only when it cannot be reached; a negative answer from it is
    final. Raises ``HostnameException("not_resolving")`` when nothing answers.
    """
    try:
        source = resolver if resolver is not None else dns.resolver
        return list(source.resolve(fqdn, rdtype))
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return []
    except dns.exception.DNSException:
        if resolver is None:
            raise HostnameException("not_resolving")
    # Authoritative servers unreachable (e.g. egress to port 53 is blocked).
    try:
        return list(dns.resolver.resolve(fqdn, rdtype))
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return []
    except dns.exception.DNSException:
        raise HostnameException("not_resolving")


def _addresses(fqdn: str, resolver: dns.resolver.Resolver | None) -> set[IPAddress]:
    return {
        ipaddress.ip_address(record.address)
        for rdtype in ("A", "AAAA")
        for record in _lookup(fqdn, rdtype, resolver)
    }


def cname_target(settings: CaelusSettings) -> str:
    """The name custom domains are told to point at: the tenant domain, which
    the platform keeps pointed at its edge."""
    return settings.tenant_domain or settings.domain


def _check_dns_target(fqdn: str, settings: CaelusSettings) -> None:
    """Require a custom hostname to reach the platform: a CNAME to
    :func:`cname_target`, or failing that, A/AAAA records that are all among
    its own addresses (an apex cannot carry a CNAME).
    """
    if not settings.domain:
        return
    target_domain = cname_target(settings)

    # Query the zone's authoritative nameservers directly so a record created
    # *after* a first failed check is picked up immediately, instead of waiting
    # out a recursive resolver's negative cache.
    resolver = _authoritative_resolver(fqdn)
    cname = _lookup(fqdn, "CNAME", resolver)
    if cname:
        target = cname[0].target.to_text().rstrip(".").lower()
        if target != target_domain.lower():
            raise HostnameException("not_resolving")
        return

    addresses = _addresses(fqdn, resolver)
    if not addresses:
        raise HostnameException("not_resolving")
    # The platform's own records, from its authoritative servers too: the
    # cluster's resolver may answer for the platform domain differently.
    platform = _addresses(target_domain, _authoritative_resolver(target_domain))
    if not addresses <= platform:
        raise HostnameException("not_resolving")


def require_valid_hostname_for_deployment(
    session: Session,
    fqdn: str,
    *,
    handle: str | None,
    exclude_deployment_id: UUID | None = None,
    settings: CaelusSettings | None = None,
) -> str:
    """Validate that *fqdn* can be used for a new or updated deployment owned
    by an account holding *handle*, and return the completed, lowercased name.

    Raises ``HostnameException(reason=...)`` on the first failing check. A bare
    label is completed beneath the handle first; then format, and under the
    tenant domain the tenant pattern, ownership, the preview reservation and
    availability. Anywhere else: the platform-domain refusal, availability,
    and the DNS target (CNAME, or A/AAAA records on the platform's addresses).
    Tenant hostnames need no DNS check: the platform serves them itself.

    Pass *exclude_deployment_id* when updating an existing deployment so its
    own hostname doesn't trigger an "in_use" conflict.
    """
    settings = settings or get_settings()
    fqdn = complete_hostname(fqdn, handle=handle, settings=settings)
    _check_format(fqdn)
    if _under(fqdn, settings.tenant_domain):
        _check_tenant_label(fqdn, handle=handle, settings=settings)
        _check_available(session, fqdn, exclude_deployment_id=exclude_deployment_id)
        return fqdn
    if any(_under(fqdn, domain) for domain in settings.platform_domains):
        raise HostnameException("reserved")
    _check_available(session, fqdn, exclude_deployment_id=exclude_deployment_id)
    _check_dns_target(fqdn, settings)
    return fqdn
