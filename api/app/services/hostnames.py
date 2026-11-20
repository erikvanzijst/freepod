from __future__ import annotations

import ipaddress
import logging
import re
from dataclasses import dataclass
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

CLOUDFLARE = "cloudflare"

# https://www.cloudflare.com/ips/
CLOUDFLARE_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "173.245.48.0/20",
        "103.21.244.0/22",
        "103.22.200.0/22",
        "103.31.4.0/22",
        "141.101.64.0/18",
        "108.162.192.0/18",
        "190.93.240.0/20",
        "188.114.96.0/20",
        "197.234.240.0/22",
        "198.41.128.0/17",
        "162.158.0.0/15",
        "104.16.0.0/13",
        "104.24.0.0/14",
        "172.64.0.0/13",
        "131.0.72.0/22",
        "2400:cb00::/32",
        "2606:4700::/32",
        "2803:f800::/32",
        "2405:b500::/32",
        "2405:8100::/32",
        "2a06:98c0::/29",
        "2c0f:f248::/32",
    )
)

OWNERSHIP_RECORD_PREFIX = "_freepod."


@dataclass(frozen=True)
class HostnameVerdict:
    fqdn: str
    proxy: str | None = None


@dataclass(frozen=True)
class OwnershipRecord:
    name: str
    value: str


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


def ownership_record(
    fqdn: str, *, handle: str | None, settings: CaelusSettings | None = None
) -> OwnershipRecord | None:
    """The TXT record that proves the owner holding *handle* controls *fqdn*'s
    DNS, which a proxied record's addresses cannot. ``None`` without a handle.
    """
    if not handle:
        return None
    settings = settings or get_settings()
    return OwnershipRecord(
        name=f"{OWNERSHIP_RECORD_PREFIX}{fqdn}",
        value=f"{handle}.{cname_target(settings)}".lower(),
    )


def _is_cloudflare(address: IPAddress) -> bool:
    return any(address in network for network in CLOUDFLARE_NETWORKS)


def _txt_text(record) -> str:
    return b"".join(record.strings).decode("ascii", "replace").strip().rstrip(".").lower()


def _check_ownership(
    fqdn: str, *, handle: str | None, settings: CaelusSettings, resolver: dns.resolver.Resolver | None
) -> None:
    record = ownership_record(fqdn, handle=handle, settings=settings)
    if record is None or record.value not in {
        _txt_text(txt) for txt in _lookup(record.name, "TXT", resolver)
    }:
        raise HostnameException("ownership_unverified", proxy=CLOUDFLARE)


def _check_dns_target(
    fqdn: str, settings: CaelusSettings, *, handle: str | None = None
) -> str | None:
    """Require a custom hostname to reach the platform: a CNAME to
    :func:`cname_target`, or failing that, A/AAAA records that are all among
    its own addresses (an apex cannot carry a CNAME).

    A name whose addresses are all Cloudflare's is accepted as proxied, which
    hides where Cloudflare forwards it, once its ownership record names
    *handle*. Returns the proxy, or ``None`` when the name points at the
    platform directly.
    """
    if not settings.domain:
        return None
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
        return None

    addresses = _addresses(fqdn, resolver)
    if not addresses:
        raise HostnameException("not_resolving")
    # The platform's own records, from its authoritative servers too: the
    # cluster's resolver may answer for the platform domain differently.
    platform = _addresses(target_domain, _authoritative_resolver(target_domain))
    if addresses <= platform:
        return None
    if all(_is_cloudflare(address) for address in addresses):
        _check_ownership(fqdn, handle=handle, settings=settings, resolver=resolver)
        return CLOUDFLARE
    raise HostnameException("not_resolving")


def check_hostname_for_deployment(
    session: Session,
    fqdn: str,
    *,
    handle: str | None,
    exclude_deployment_id: UUID | None = None,
    settings: CaelusSettings | None = None,
) -> HostnameVerdict:
    """Validate that *fqdn* can be used for a new or updated deployment owned
    by an account holding *handle*: the completed, lowercased name, and the
    proxy it is reached through, if any.

    Raises ``HostnameException(reason=...)`` on the first failing check. A bare
    label is completed beneath the handle first; then format, and under the
    tenant domain the tenant pattern, ownership, the preview reservation and
    availability. Anywhere else: the platform-domain refusal, availability,
    and the DNS target (CNAME, A/AAAA records on the platform's addresses, or
    proxied through Cloudflare with an ownership record). Tenant hostnames
    need no DNS check: the platform serves them itself.

    Pass *exclude_deployment_id* when updating an existing deployment so its
    own hostname doesn't trigger an "in_use" conflict.
    """
    settings = settings or get_settings()
    fqdn = complete_hostname(fqdn, handle=handle, settings=settings)
    _check_format(fqdn)
    if _under(fqdn, settings.tenant_domain):
        _check_tenant_label(fqdn, handle=handle, settings=settings)
        _check_available(session, fqdn, exclude_deployment_id=exclude_deployment_id)
        return HostnameVerdict(fqdn)
    if any(_under(fqdn, domain) for domain in settings.platform_domains):
        raise HostnameException("reserved")
    _check_available(session, fqdn, exclude_deployment_id=exclude_deployment_id)
    return HostnameVerdict(fqdn, proxy=_check_dns_target(fqdn, settings, handle=handle))


def require_valid_hostname_for_deployment(
    session: Session,
    fqdn: str,
    *,
    handle: str | None,
    exclude_deployment_id: UUID | None = None,
    settings: CaelusSettings | None = None,
) -> str:
    """:func:`check_hostname_for_deployment`, returning only the name."""
    return check_hostname_for_deployment(
        session,
        fqdn,
        handle=handle,
        exclude_deployment_id=exclude_deployment_id,
        settings=settings,
    ).fqdn
