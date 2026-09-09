from __future__ import annotations

import re
import logging
from uuid import UUID

import dns.exception
import dns.resolver
from sqlalchemy import func
from sqlmodel import Session, select

from app.config import CaelusSettings, get_settings
from app.models import DeploymentORM, UserORM
from app.services.errors import HostnameException
from app.services.reconcile_constants import DEPLOYMENT_STATUS_DELETED

logger = logging.getLogger(__name__)

# RFC 952/1123: labels are 1-63 chars, alphanumeric + hyphens, no leading/trailing hyphens.
# Total FQDN max 253 chars.
_LABEL_RE = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$")

# An account subdomain is 2-63 characters: 63 is the same RFC 1035 label limit,
# and the lower bound holds single characters back for the platform.
SUBDOMAIN_MIN_LENGTH = 2
SUBDOMAIN_MAX_LENGTH = 63
_SUBDOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$")


def _check_format(fqdn: str) -> None:
    if not fqdn or len(fqdn) > 253:
        raise HostnameException("invalid")
    labels = fqdn.rstrip(".").split(".")
    if len(labels) < 2:
        raise HostnameException("invalid")
    for label in labels:
        if not label or not _LABEL_RE.match(label):
            raise HostnameException("invalid")


def wildcard_prefix(fqdn: str, settings: CaelusSettings) -> list[str] | None:
    """The labels *fqdn* places under a configured wildcard domain, or ``None``
    when it is not under one at all.

    One label is an account subdomain, two are an application beneath one. The
    two namespaces are separated by depth alone, so this is what tells them
    apart everywhere.
    """
    for domain in settings.wildcard_domains:
        if fqdn == domain:
            return []
        if fqdn.endswith(f".{domain}"):
            return fqdn[: -(len(domain) + 1)].split(".")
    return None


def _check_wildcard_depth(fqdn: str, settings: CaelusSettings) -> None:
    labels = wildcard_prefix(fqdn, settings)
    if labels is not None and len(labels) != 2:
        raise HostnameException("invalid")


def _check_reserved(fqdn: str, settings: CaelusSettings) -> None:
    if fqdn in settings.reserved_hostnames:
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


def _check_subdomain_format(label: str) -> None:
    if not _SUBDOMAIN_RE.match(label):
        raise HostnameException("invalid")


def _check_subdomain_reserved(label: str, settings: CaelusSettings) -> None:
    for domain in settings.wildcard_domains:
        if f"{label}.{domain}" in settings.reserved_hostnames:
            raise HostnameException("reserved")


def _check_subdomain_claimed(session: Session, label: str) -> None:
    # Deliberately unfiltered by `deleted_at`: a deleted account keeps its
    # label rather than releasing it back into circulation.
    held = session.exec(
        select(UserORM.id).where(func.lower(UserORM.subdomain) == label)
    ).first()
    if held is not None:
        raise HostnameException("claimed")


def require_valid_subdomain(
    session: Session,
    label: str,
    *,
    settings: CaelusSettings | None = None,
) -> None:
    """Validate that *label* can be claimed as an account subdomain.

    Raises ``HostnameException(reason=...)`` on the first failing check.
    Checks run in order: format, reserved, claimed.

    The deployments table is never consulted: an application is addressed one
    label further down, so no deployment hostname can contend with a claim.
    """
    settings = settings or get_settings()
    label = label.lower()
    _check_subdomain_format(label)
    _check_subdomain_reserved(label, settings)
    _check_subdomain_claimed(session, label)


def _authoritative_resolver(fqdn: str) -> dns.resolver.Resolver | None:
    """Build a resolver that queries the authoritative nameservers for *fqdn*
    directly, bypassing any recursive resolver's cache — including the negative
    cache that would otherwise pin a "no such CNAME" answer for the zone's SOA
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


def _check_cname(fqdn: str, settings: CaelusSettings) -> None:
    if not settings.domain:
        return

    # Wildcard subdomains are served by platform-managed A records, not a
    # user-delegated CNAME, so they bypass the CNAME requirement entirely.
    for domain in settings.wildcard_domains:
        if fqdn == domain or fqdn.endswith(f".{domain}"):
            return

    # Query the zone's authoritative nameservers directly so a user who creates
    # the CNAME *after* a first failed check is picked up immediately, instead
    # of waiting out a recursive resolver's negative cache.
    resolver = _authoritative_resolver(fqdn)
    try:
        source = resolver if resolver is not None else dns.resolver
        answer = source.resolve(fqdn, "CNAME")
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        # Definitive answer from the authoritative server: no matching CNAME.
        raise HostnameException("not_resolving")
    except dns.exception.DNSException:
        if resolver is None:
            raise HostnameException("not_resolving")
        # Couldn't reach the authoritative servers (e.g. egress to port 53 is
        # blocked); fall back to the system resolver before giving up.
        try:
            answer = dns.resolver.resolve(fqdn, "CNAME")
        except dns.exception.DNSException:
            raise HostnameException("not_resolving")

    target = answer[0].target.to_text().rstrip(".").lower()
    if target != settings.domain.lower():
        raise HostnameException("not_resolving")


def require_owned_subdomain(
    fqdn: str,
    *,
    subdomain: str | None,
    settings: CaelusSettings | None = None,
) -> None:
    """Refuse a wildcard-domain hostname sitting under another account's
    subdomain, raising ``HostnameException("claimed")``.

    Separate from the validation sequence because it needs the owner, which a
    session and an FQDN do not supply (D10). Hostnames outside every configured
    wildcard domain are the user's own DNS and are not subject to it.
    """
    settings = settings or get_settings()
    labels = wildcard_prefix(fqdn.lower(), settings)
    if labels is None or len(labels) != 2:
        return
    if labels[1] != (subdomain or "").lower():
        raise HostnameException("claimed")


def require_valid_hostname_for_deployment(
    session: Session,
    fqdn: str,
    *,
    exclude_deployment_id: UUID | None = None,
    settings: CaelusSettings | None = None,
) -> None:
    """Validate that *fqdn* can be used for a new or updated deployment.

    Raises ``HostnameException(reason=...)`` on the first failing check.
    Checks run in order: format → wildcard depth → reserved → availability →
    DNS CNAME.

    Pass *exclude_deployment_id* when updating an existing deployment so its
    own hostname doesn't trigger an "in_use" conflict.
    """
    settings = settings or get_settings()
    fqdn = fqdn.lower()
    _check_format(fqdn)
    _check_wildcard_depth(fqdn, settings)
    _check_reserved(fqdn, settings)
    _check_available(session, fqdn, exclude_deployment_id=exclude_deployment_id)
    _check_cname(fqdn, settings)


def check_hostname_availability(
    session: Session,
    fqdn: str,
    *,
    subdomain: str | None,
    settings: CaelusSettings | None = None,
) -> None:
    """Validate *fqdn* as whatever its depth says it is, for a caller holding
    *subdomain*.

    A single label under a configured wildcard domain is an account subdomain;
    anything else is a deployment hostname, which must sit under the caller's
    own subdomain when it is under a wildcard domain at all.
    """
    settings = settings or get_settings()
    fqdn = fqdn.lower()
    labels = wildcard_prefix(fqdn, settings)
    if labels is not None and len(labels) == 1:
        require_valid_subdomain(session, labels[0], settings=settings)
        return
    require_owned_subdomain(fqdn, subdomain=subdomain, settings=settings)
    require_valid_hostname_for_deployment(session, fqdn, settings=settings)
