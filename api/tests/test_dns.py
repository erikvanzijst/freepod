"""The DNS adapter, exercised against a fake rather than a live zone."""

from __future__ import annotations

import inspect

import pytest
from app.config import CaelusSettings
from app.services import dns
from app.services.dns import CloudflareDns, DnsException, DnsProvider


class FakeRecords:
    def __init__(self, existing: list[str] | None = None) -> None:
        self.records = list(existing or [])
        self.list_calls: list[dict] = []
        self.create_calls: list[dict] = []
        self.fail_with: Exception | None = None

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        if self.fail_with is not None:
            raise self.fail_with
        wanted = kwargs["name"]["exact"]
        return [{"name": name} for name in self.records if name == wanted]

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        if self.fail_with is not None:
            raise self.fail_with
        self.records.append(kwargs["name"])
        return {"name": kwargs["name"]}


class FakeClient:
    def __init__(self, existing: list[str] | None = None) -> None:
        self.dns = type("_Dns", (), {})()
        self.dns.records = FakeRecords(existing)


def make_provider(existing: list[str] | None = None) -> tuple[CloudflareDns, FakeClient]:
    client = FakeClient(existing)
    provider = CloudflareDns(
        api_token="unused",
        zone_id="zone123",
        target="kube.freepod.eu",
        client=client,
    )
    return provider, client


def test_interface_names_no_provider():
    for name in ("wildcard_record_exists", "ensure_wildcard_record"):
        signature = inspect.signature(getattr(DnsProvider, name))
        rendered = str(signature).lower()
        for leak in ("cloudflare", "hetzner", "zone_id", "record", "client"):
            assert leak not in rendered, f"{name}{signature} leaks {leak!r}"


def test_creates_the_wildcard_not_the_bare_name():
    provider, client = make_provider()
    provider.ensure_wildcard_record("erik.dev.freepod.eu")
    assert [c["name"] for c in client.dns.records.create_calls] == ["*.erik.dev.freepod.eu"]


def test_created_record_mirrors_the_platform_wildcard():
    provider, client = make_provider()
    provider.ensure_wildcard_record("erik.dev.freepod.eu")
    created = client.dns.records.create_calls[0]
    assert created["type"] == "CNAME"
    assert created["content"] == "kube.freepod.eu"
    assert created["proxied"] is False
    assert created["zone_id"] == "zone123"


def test_ensure_is_idempotent():
    provider, client = make_provider()
    provider.ensure_wildcard_record("erik.dev.freepod.eu")
    provider.ensure_wildcard_record("erik.dev.freepod.eu")
    assert len(client.dns.records.create_calls) == 1
    assert client.dns.records.records == ["*.erik.dev.freepod.eu"]


def test_existing_record_is_not_rewritten():
    provider, client = make_provider(existing=["*.erik.dev.freepod.eu"])
    provider.ensure_wildcard_record("erik.dev.freepod.eu")
    assert client.dns.records.create_calls == []


def test_existence_is_reported_per_account():
    provider, _ = make_provider(existing=["*.erik.dev.freepod.eu"])
    assert provider.wildcard_record_exists("erik.dev.freepod.eu") is True
    assert provider.wildcard_record_exists("fred.dev.freepod.eu") is False


def test_lookup_is_filtered_server_side():
    provider, client = make_provider()
    provider.wildcard_record_exists("erik.dev.freepod.eu")
    assert client.dns.records.list_calls == [
        {"zone_id": "zone123", "name": {"exact": "*.erik.dev.freepod.eu"}, "type": "CNAME"}
    ]


def test_provider_errors_do_not_escape_as_provider_errors():
    class CloudflareAPIError(Exception):
        pass

    provider, client = make_provider()
    client.dns.records.fail_with = CloudflareAPIError("429 too many requests")

    with pytest.raises(DnsException) as read:
        provider.wildcard_record_exists("erik.dev.freepod.eu")
    assert "429 too many requests" in str(read.value)

    with pytest.raises(DnsException):
        provider.ensure_wildcard_record("erik.dev.freepod.eu")


def test_unconfigured_environment_reports_rather_than_starts():
    settings = CaelusSettings(_env_file=None)
    assert dns.is_configured(settings) is False
    with pytest.raises(DnsException) as exc:
        dns.from_settings(settings)
    for name in ("cloudflare_dns_api_token", "cloudflare_dns_zone_id", "dns_record_target"):
        assert name in str(exc.value)


def test_configured_environment_builds_a_provider(monkeypatch):
    settings = CaelusSettings(
        _env_file=None,
        cloudflare_dns_api_token="token",
        cloudflare_dns_zone_id="zone123",
        dns_record_target="kube.freepod.eu",
    )
    assert dns.is_configured(settings) is True

    built = {}

    class FakeCloudflare:
        def __init__(self, *, api_token):
            built["api_token"] = api_token

    monkeypatch.setitem(__import__("sys").modules, "cloudflare", type("_M", (), {"Cloudflare": FakeCloudflare}))
    provider = dns.from_settings(settings)
    assert isinstance(provider, CloudflareDns)
    assert built["api_token"] == "token"
