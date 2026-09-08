"""The platform's DNS writes, behind one narrow interface.

Every account that deploys gets a wildcard record for its own subdomain, and it
is load-bearing rather than convenient: see
openspec/specs/account-dns-record/spec.md. Nothing provider-shaped leaves this
module, so a change of provider is a new implementation and a config value.
"""

from __future__ import annotations

import logging
from typing import Protocol

from app.config import CaelusSettings, get_settings
from app.services.errors import CaelusException

logger = logging.getLogger(__name__)

_TTL_AUTOMATIC = 1


class DnsException(CaelusException):
    """A DNS write failed, or no provider is configured."""


def wildcard_of(name: str) -> str:
    """The wildcard record name covering every host under *name*."""
    return f"*.{name}"


class DnsProvider(Protocol):
    """Names are an account's own fully qualified name, never the wildcard."""

    def wildcard_record_exists(self, name: str) -> bool:
        """Whether a wildcard record covering hosts under *name* is present."""
        ...

    def ensure_wildcard_record(self, name: str) -> None:
        """Create that record if it is absent. Idempotent, and never rewrites."""
        ...


class CloudflareDns:
    """`DnsProvider` over Cloudflare's official SDK."""

    def __init__(
        self, *, api_token: str, zone_id: str, target: str, client: object | None = None
    ) -> None:
        self._zone_id = zone_id
        self._target = target
        if client is None:
            from cloudflare import Cloudflare

            client = Cloudflare(api_token=api_token)
        self._client = client

    @classmethod
    def from_settings(cls, settings: CaelusSettings | None = None) -> CloudflareDns:
        settings = settings or get_settings()
        missing = [
            name
            for name in ("cloudflare_dns_api_token", "cloudflare_dns_zone_id", "dns_record_target")
            if not getattr(settings, name)
        ]
        if missing:
            raise DnsException(
                "DNS provider is not configured: missing " + ", ".join(sorted(missing))
            )
        return cls(
            api_token=settings.cloudflare_dns_api_token,
            zone_id=settings.cloudflare_dns_zone_id,
            target=settings.dns_record_target,
        )

    def wildcard_record_exists(self, name: str) -> bool:
        return self._find(wildcard_of(name)) is not None

    def ensure_wildcard_record(self, name: str) -> None:
        record_name = wildcard_of(name)
        if self._find(record_name) is not None:
            return
        try:
            self._client.dns.records.create(
                zone_id=self._zone_id,
                name=record_name,
                type="CNAME",
                content=self._target,
                ttl=_TTL_AUTOMATIC,
                proxied=False,
            )
        except Exception as exc:
            raise DnsException(f"Could not create DNS record {record_name}: {exc}") from exc
        logger.info("Created wildcard DNS record %s -> %s", record_name, self._target)

    def _find(self, record_name: str) -> object | None:
        try:
            page = self._client.dns.records.list(
                zone_id=self._zone_id,
                name={"exact": record_name},
                type="CNAME",
            )
            records = list(page)
        except Exception as exc:
            raise DnsException(f"Could not read DNS records for {record_name}: {exc}") from exc
        return records[0] if records else None


def is_configured(settings: CaelusSettings | None = None) -> bool:
    settings = settings or get_settings()
    return bool(
        settings.cloudflare_dns_api_token
        and settings.cloudflare_dns_zone_id
        and settings.dns_record_target
    )


def from_settings(settings: CaelusSettings | None = None) -> DnsProvider:
    return CloudflareDns.from_settings(settings)
