"""Tests for the hostname validation service and API endpoint."""
from unittest.mock import Mock, patch
from uuid import UUID

import dns.exception
import dns.resolver
import pytest

from app.config import CaelusSettings
from app.services.errors import HostnameException
from app.services.hostnames import (
    _check_format,
    _check_available,
    _check_dns_target,
    require_valid_hostname_for_deployment,
)
from app.db import get_session
from app.main import app as fastapi_app
from app.models import DeploymentORM, DeploymentReconcileJobORM, UserORM, ProductORM, ProductTemplateVersionORM
from app.services.jobs import JobService
from app.services.reconcile_constants import (
    DEPLOYMENT_STATUS_PROVISIONING,
    DEPLOYMENT_STATUS_DELETED,
)
from sqlmodel import select
from starlette.testclient import TestClient

from tests.conftest import client, db_session
from tests.conftest import create_free_plan_template, create_user, make_deployment_with_release


def _settings(**overrides) -> CaelusSettings:
    """Build a CaelusSettings with test defaults, ignoring env vars."""
    defaults = {"domain": ""}
    return CaelusSettings(**{**defaults, **overrides}, _env_file=None)


@pytest.fixture
def seed_parents(db_session):
    """Create the minimum parent rows (user, product, template) so that
    DeploymentORM inserts satisfy foreign key constraints."""
    user = UserORM(email="seed@example.com")
    db_session.add(user)
    db_session.flush()

    product = ProductORM(name="seed-product")
    db_session.add(product)
    db_session.flush()

    template = ProductTemplateVersionORM(
        product_id=product.id,
        chart_ref="oci://example/seed",
        chart_version="1.0.0",
    )
    db_session.add(template)
    db_session.flush()

    return {"user_id": user.id, "template_id": template.id}


# ── Format check ──────────────────────────────────────────────────────


class TestCheckFormat:
    def test_valid_fqdn(self):
        _check_format("myapp.example.com")

    def test_valid_fqdn_with_trailing_dot(self):
        _check_format("myapp.example.com.")

    def test_valid_single_char_labels(self):
        _check_format("a.b.com")

    def test_valid_hyphens_in_middle(self):
        _check_format("my-app.ex-ample.com")

    def test_rejects_empty_string(self):
        with pytest.raises(HostnameException, match="invalid"):
            _check_format("")

    def test_rejects_single_label(self):
        with pytest.raises(HostnameException, match="invalid"):
            _check_format("localhost")

    def test_rejects_too_long(self):
        fqdn = "a" * 64 + ".example.com"  # label > 63 chars
        with pytest.raises(HostnameException, match="invalid"):
            _check_format(fqdn)

    def test_rejects_total_too_long(self):
        fqdn = ".".join(["a" * 50] * 6)  # 50*6 + 5 dots = 305 chars
        with pytest.raises(HostnameException, match="invalid"):
            _check_format(fqdn)

    def test_rejects_leading_hyphen(self):
        with pytest.raises(HostnameException, match="invalid"):
            _check_format("-bad.example.com")

    def test_rejects_trailing_hyphen(self):
        with pytest.raises(HostnameException, match="invalid"):
            _check_format("bad-.example.com")

    def test_rejects_empty_label(self):
        with pytest.raises(HostnameException, match="invalid"):
            _check_format("bad..example.com")

    def test_rejects_underscore(self):
        with pytest.raises(HostnameException, match="invalid"):
            _check_format("bad_host.example.com")

    def test_rejects_space(self):
        with pytest.raises(HostnameException, match="invalid"):
            _check_format("bad host.example.com")


# ── Tenant hostnames ──────────────────────────────────────────────────


TENANT = {"tenant_domain": "freepod.app", "platform_domains": ["freepod.eu", "freepod.app"]}


def _validate(session, value, *, handle="alice", **overrides):
    return require_valid_hostname_for_deployment(
        session, value, handle=handle, settings=_settings(**{**TENANT, **overrides})
    )


def _reason(session, value, **kwargs) -> str:
    with pytest.raises(HostnameException) as exc_info:
        _validate(session, value, **kwargs)
    return exc_info.value.reason


class TestTenantHostname:
    def test_bare_label_is_completed(self, db_session):
        assert _validate(db_session, "photos") == "photos-alice.freepod.app"

    def test_bare_label_is_lowercased_then_completed(self, db_session):
        assert _validate(db_session, "Photos") == "photos-alice.freepod.app"

    def test_own_fqdn_is_checked_as_given(self, db_session):
        assert _validate(db_session, "photos-alice.freepod.app") == "photos-alice.freepod.app"

    def test_dashes_in_the_application_part(self, db_session):
        assert _validate(db_session, "my-photos-alice.freepod.app") == "my-photos-alice.freepod.app"

    def test_bare_label_without_a_handle_is_invalid(self, db_session):
        assert _reason(db_session, "photos", handle=None) == "invalid"

    def test_another_accounts_handle_is_claimed(self, db_session):
        assert _reason(db_session, "photos-alice.freepod.app", handle="bob") == "claimed"

    def test_claimed_skips_availability(self, db_session):
        with patch("app.services.hostnames._check_available") as available:
            assert _reason(db_session, "photos-alice.freepod.app", handle="bob") == "claimed"
        available.assert_not_called()

    @pytest.mark.parametrize("value", ["photos.freepod.app", "alice.freepod.app"])
    def test_label_without_a_handle_segment_is_invalid(self, db_session, value):
        assert _reason(db_session, value) == "invalid"

    def test_nested_name_is_invalid(self, db_session):
        assert _reason(db_session, "a.photos-alice.freepod.app") == "invalid"

    def test_double_dash_is_invalid(self, db_session):
        assert _reason(db_session, "my--photos-alice.freepod.app") == "invalid"

    def test_application_part_limit(self, db_session):
        assert _validate(db_session, f"{'a' * 34}-alice.freepod.app")
        assert _reason(db_session, f"{'a' * 35}-alice.freepod.app") == "invalid"

    def test_malformed_handle_segment_is_invalid(self, db_session):
        assert _reason(db_session, "photos-a.freepod.app", handle="a") == "invalid"

    def test_tenant_domain_itself_is_invalid(self, db_session):
        assert _reason(db_session, "freepod.app") == "invalid"

    def test_malformed_label_skips_ownership_and_availability(self, db_session):
        with patch("app.services.hostnames._check_available") as available:
            assert _reason(db_session, "my--photos-bob.freepod.app") == "invalid"
        available.assert_not_called()

    def test_preview_label_is_reserved(self, db_session):
        assert _reason(db_session, "Preview-Studio-alice.freepod.app") == "reserved"

    def test_preview_must_start_the_label(self, db_session):
        assert _validate(db_session, "mypreview-app-alice.freepod.app")

    def test_preview_on_a_custom_domain_is_not_this_rule(self, db_session):
        assert _validate(db_session, "preview-app.example.com")

    def test_no_dns_check_for_tenant_hostnames(self, db_session):
        with patch("app.services.hostnames._check_dns_target") as dns_check:
            _validate(db_session, "photos", domain="freepod.eu")
        dns_check.assert_not_called()

    def test_in_use(self, db_session, seed_parents):
        make_deployment_with_release(
            db_session,
            user_id=seed_parents["user_id"],
            desired_template_id=seed_parents["template_id"],
            hostname="photos-alice.freepod.app",
            status=DEPLOYMENT_STATUS_PROVISIONING,
            name="tenant-in-use",
            namespace="tenant-in-use",
        )
        db_session.flush()
        assert _reason(db_session, "photos") == "in_use"


class TestPlatformDomains:
    @pytest.mark.parametrize(
        "value", ["grafana.freepod.eu", "SMTP.freepod.eu", "freepod.eu", "photos.alice.freepod.eu"]
    )
    def test_names_under_a_platform_domain_are_reserved(self, db_session, value):
        assert _reason(db_session, value) == "reserved"

    def test_the_other_environments_tenant_name_is_reserved(self, db_session):
        assert _reason(db_session, "photos-alice.freepod.app", tenant_domain="dev.freepod.app") == "reserved"

    def test_this_environments_tenant_name_under_a_platform_domain(self, db_session):
        assert _validate(db_session, "photos", tenant_domain="dev.freepod.app") == "photos-alice.dev.freepod.app"

    def test_reserved_skips_availability_and_dns(self, db_session):
        with patch("app.services.hostnames._check_available") as available, patch(
            "app.services.hostnames._check_dns_target"
        ) as dns_check:
            assert _reason(db_session, "grafana.freepod.eu", domain="freepod.eu") == "reserved"
        available.assert_not_called()
        dns_check.assert_not_called()

    def test_custom_domain_is_unaffected(self, db_session):
        assert _validate(db_session, "photos.example.com") == "photos.example.com"


# ── Availability check ────────────────────────────────────────────────


class TestCheckAvailable:
    def test_available_passes(self, db_session):
        _check_available(db_session, "free.example.com")

    def test_in_use_raises(self, db_session, seed_parents):
        dep = make_deployment_with_release(
            db_session,
            user_id=seed_parents["user_id"],
            desired_template_id=seed_parents["template_id"],
            hostname="taken.example.com",
            status=DEPLOYMENT_STATUS_PROVISIONING,
            name="test-name",
            namespace="test-namespace",
        )
        db_session.flush()
        with pytest.raises(HostnameException, match="in_use"):
            _check_available(db_session, "taken.example.com")

    def test_deleted_deployment_not_in_use(self, db_session, seed_parents):
        dep = make_deployment_with_release(
            db_session,
            user_id=seed_parents["user_id"],
            desired_template_id=seed_parents["template_id"],
            hostname="recycled.example.com",
            status=DEPLOYMENT_STATUS_DELETED,
            name="test-name-2",
            namespace="test-namespace-2",
        )
        db_session.flush()
        _check_available(db_session, "recycled.example.com")


# ── DNS target check ──────────────────────────────────────────────────


def _cname_answer(target: str):
    """Build a fake CNAME query result whose single rdata's target renders to
    *target* (with the trailing-dot FQDN form dnspython produces)."""
    rdata = Mock()
    rdata.target.to_text.return_value = f"{target}."
    return [rdata]


@pytest.fixture
def no_authoritative():
    """Force the system-resolver fallback path so a test can drive validation
    through the module-level ``dns.resolver.resolve`` mock without standing up
    fake authoritative nameservers."""
    with patch("app.services.hostnames._authoritative_resolver", return_value=None):
        yield


class TestCheckCname:
    def test_passes_when_cname_matches_exactly(self, no_authoritative):
        with patch(
            "app.services.hostnames.dns.resolver.resolve",
            return_value=_cname_answer("freepod.eu"),
        ):
            _check_dns_target("good.example.com", _settings(domain="freepod.eu"))

    def test_fails_when_cname_points_to_subdomain_of_domain(self, no_authoritative):
        with patch(
            "app.services.hostnames.dns.resolver.resolve",
            return_value=_cname_answer("ingress.freepod.eu"),
        ):
            with pytest.raises(HostnameException, match="not_resolving"):
                _check_dns_target("sub.example.com", _settings(domain="freepod.eu"))

    def test_fails_when_no_records_at_all(self, no_authoritative):
        with patch(
            "app.services.hostnames.dns.resolver.resolve",
            side_effect=dns.resolver.NoAnswer,
        ):
            with pytest.raises(HostnameException, match="not_resolving"):
                _check_dns_target("empty.example.com", _settings(domain="freepod.eu"))

    def test_fails_when_cname_points_to_wrong_target(self, no_authoritative):
        with patch(
            "app.services.hostnames.dns.resolver.resolve",
            return_value=_cname_answer("somewhere-else.example.net"),
        ):
            with pytest.raises(HostnameException, match="not_resolving"):
                _check_dns_target("wrong.example.com", _settings(domain="freepod.eu"))

    def test_fails_on_nxdomain(self, no_authoritative):
        with patch(
            "app.services.hostnames.dns.resolver.resolve",
            side_effect=dns.resolver.NXDOMAIN,
        ):
            with pytest.raises(HostnameException, match="not_resolving"):
                _check_dns_target("nxdomain.example.com", _settings(domain="freepod.eu"))

    def test_fails_on_timeout(self, no_authoritative):
        with patch(
            "app.services.hostnames.dns.resolver.resolve",
            side_effect=dns.exception.Timeout,
        ):
            with pytest.raises(HostnameException, match="not_resolving"):
                _check_dns_target("slow.example.com", _settings(domain="freepod.eu"))

    def test_skipped_when_domain_empty(self):
        # Should not raise or even query DNS when domain is unconfigured
        with patch("app.services.hostnames._authoritative_resolver") as mock_auth, patch(
            "app.services.hostnames.dns.resolver.resolve"
        ) as mock_resolve:
            _check_dns_target("nonexistent.example.test", _settings(domain=""))
        mock_auth.assert_not_called()
        mock_resolve.assert_not_called()

    def test_queries_authoritative_and_bypasses_recursive_resolver(self):
        """The CNAME is read from the authoritative servers, not the cache-prone
        system resolver — so a freshly created record is seen immediately."""
        auth = Mock()
        auth.resolve.return_value = _cname_answer("freepod.eu")
        with patch(
            "app.services.hostnames._authoritative_resolver", return_value=auth
        ), patch("app.services.hostnames.dns.resolver.resolve") as module_resolve:
            _check_dns_target("good.example.com", _settings(domain="freepod.eu"))
        auth.resolve.assert_called_once_with("good.example.com", "CNAME")
        module_resolve.assert_not_called()

    def test_authoritative_negative_answer_does_not_fall_back(self):
        """An NXDOMAIN straight from the authoritative server is definitive; we
        must not retry via the (potentially stale) system resolver."""
        auth = Mock()
        auth.resolve.side_effect = dns.resolver.NXDOMAIN
        with patch(
            "app.services.hostnames._authoritative_resolver", return_value=auth
        ), patch("app.services.hostnames.dns.resolver.resolve") as module_resolve:
            with pytest.raises(HostnameException, match="not_resolving"):
                _check_dns_target("nope.example.com", _settings(domain="freepod.eu"))
        module_resolve.assert_not_called()

    def test_falls_back_to_system_resolver_when_authoritative_unreachable(self):
        """If the authoritative servers can't be reached (e.g. egress blocked),
        degrade to the system resolver rather than failing the check."""
        auth = Mock()
        auth.resolve.side_effect = dns.exception.Timeout
        with patch(
            "app.services.hostnames._authoritative_resolver", return_value=auth
        ), patch(
            "app.services.hostnames.dns.resolver.resolve",
            return_value=_cname_answer("freepod.eu"),
        ):
            _check_dns_target("good.example.com", _settings(domain="freepod.eu"))


PLATFORM_V4 = "185.142.224.235"
PLATFORM_V6 = "2001:db8::1"


def _address_answer(*addresses: str):
    return [Mock(address=a) for a in addresses]


def _fake_dns(records: dict[tuple[str, str], list[str]]):
    """A ``resolve`` side effect answering from *records*, keyed by (name,
    type); A/AAAA values are addresses, a CNAME value is its target. Anything
    absent is a definitive NoAnswer, as an authoritative server would say."""

    def resolve(name, rdtype):
        values = records.get((name, rdtype))
        if not values:
            raise dns.resolver.NoAnswer
        if rdtype == "CNAME":
            return _cname_answer(values[0])
        return _address_answer(*values)

    return resolve


class TestTenantDomainTarget:
    """Custom domains point at the tenant domain, and nowhere else."""

    SETTINGS = {"domain": "freepod.eu", "tenant_domain": "freepod.app"}

    @pytest.mark.parametrize("target", ["freepod.app", "FREEPOD.APP"])
    def test_the_tenant_domain_passes(self, no_authoritative, target):
        with patch(
            "app.services.hostnames.dns.resolver.resolve",
            side_effect=_fake_dns({("good.example.com", "CNAME"): [target]}),
        ):
            _check_dns_target("good.example.com", _settings(**self.SETTINGS))

    @pytest.mark.parametrize(
        "target", ["freepod.eu", "x.freepod.app", "dev.freepod.app", "other.example"]
    )
    def test_any_other_target_fails(self, no_authoritative, target):
        with patch(
            "app.services.hostnames.dns.resolver.resolve",
            side_effect=_fake_dns({("bad.example.com", "CNAME"): [target]}),
        ):
            with pytest.raises(HostnameException, match="not_resolving"):
                _check_dns_target("bad.example.com", _settings(**self.SETTINGS))

    def test_addresses_are_compared_with_the_tenant_domains(self, no_authoritative):
        records = {("freepod.app", "A"): [PLATFORM_V4], ("example.com", "A"): [PLATFORM_V4]}
        with patch(
            "app.services.hostnames.dns.resolver.resolve", side_effect=_fake_dns(records)
        ):
            _check_dns_target("example.com", _settings(**self.SETTINGS))


class TestCheckAddressRecords:
    """Apex domains cannot carry a CNAME; A/AAAA records on the platform's own
    addresses are accepted instead."""

    def _check(self, fqdn: str, records: dict, *, platform: dict | None = None):
        platform = platform if platform is not None else {("freepod.eu", "A"): [PLATFORM_V4]}
        with patch(
            "app.services.hostnames.dns.resolver.resolve",
            side_effect=_fake_dns({**platform, **records}),
        ):
            _check_dns_target(fqdn, _settings(domain="freepod.eu"))

    def test_apex_a_record_on_platform_address_passes(self, no_authoritative):
        self._check("example.com", {("example.com", "A"): [PLATFORM_V4]})

    def test_a_and_aaaa_both_on_platform_pass(self, no_authoritative):
        self._check(
            "example.com",
            {("example.com", "A"): [PLATFORM_V4], ("example.com", "AAAA"): [PLATFORM_V6]},
            platform={("freepod.eu", "A"): [PLATFORM_V4], ("freepod.eu", "AAAA"): [PLATFORM_V6]},
        )

    def test_ipv4_only_passes_when_platform_is_dual_stack(self, no_authoritative):
        self._check(
            "example.com",
            {("example.com", "A"): [PLATFORM_V4]},
            platform={("freepod.eu", "A"): [PLATFORM_V4], ("freepod.eu", "AAAA"): [PLATFORM_V6]},
        )

    def test_ipv6_only_passes_when_on_platform(self, no_authoritative):
        self._check(
            "example.com",
            {("example.com", "AAAA"): ["2001:DB8:0::1"]},
            platform={("freepod.eu", "A"): [PLATFORM_V4], ("freepod.eu", "AAAA"): [PLATFORM_V6]},
        )

    def test_platform_reached_through_a_cname_chain(self, no_authoritative):
        """dev.freepod.eu is itself a CNAME; its addresses are what resolve
        returns after following it."""
        with patch(
            "app.services.hostnames.dns.resolver.resolve",
            side_effect=_fake_dns({
                ("dev.freepod.eu", "A"): [PLATFORM_V4],
                ("example.com", "A"): [PLATFORM_V4],
            }),
        ):
            _check_dns_target("example.com", _settings(domain="dev.freepod.eu"))

    def test_a_record_elsewhere_fails(self, no_authoritative):
        with pytest.raises(HostnameException, match="not_resolving"):
            self._check("example.com", {("example.com", "A"): ["203.0.113.9"]})

    def test_one_foreign_address_among_several_fails(self, no_authoritative):
        with pytest.raises(HostnameException, match="not_resolving"):
            self._check("example.com", {("example.com", "A"): [PLATFORM_V4, "203.0.113.9"]})

    def test_aaaa_elsewhere_fails_even_with_matching_a(self, no_authoritative):
        """IPv6 clients (and Let's Encrypt, which prefers IPv6) would reach the
        foreign address, so a matching A record does not redeem it."""
        with pytest.raises(HostnameException, match="not_resolving"):
            self._check(
                "example.com",
                {("example.com", "A"): [PLATFORM_V4], ("example.com", "AAAA"): ["2001:db8::dead"]},
            )

    def test_no_records_fails(self, no_authoritative):
        with pytest.raises(HostnameException, match="not_resolving"):
            self._check("example.com", {})

    def test_fails_when_platform_has_no_addresses(self, no_authoritative):
        with pytest.raises(HostnameException, match="not_resolving"):
            self._check("example.com", {("example.com", "A"): [PLATFORM_V4]}, platform={})

    def test_cname_elsewhere_is_not_rescued_by_addresses(self, no_authoritative):
        with pytest.raises(HostnameException, match="not_resolving"):
            self._check(
                "www.example.com",
                {("www.example.com", "CNAME"): ["kube.freepod.eu"], ("www.example.com", "A"): [PLATFORM_V4]},
            )

    def test_cname_to_domain_passes_without_address_lookups(self, no_authoritative):
        resolve = Mock(side_effect=_fake_dns({("www.example.com", "CNAME"): ["freepod.eu"]}))
        with patch("app.services.hostnames.dns.resolver.resolve", resolve):
            _check_dns_target("www.example.com", _settings(domain="freepod.eu"))
        resolve.assert_called_once_with("www.example.com", "CNAME")

    def test_timeout_on_address_lookup_fails(self, no_authoritative):
        def resolve(name, rdtype):
            if rdtype == "AAAA":
                raise dns.exception.Timeout
            return _fake_dns({("example.com", "A"): [PLATFORM_V4]})(name, rdtype)

        with patch("app.services.hostnames.dns.resolver.resolve", side_effect=resolve):
            with pytest.raises(HostnameException, match="not_resolving"):
                _check_dns_target("example.com", _settings(domain="freepod.eu"))

    def test_both_names_queried_at_their_authoritative_servers(self):
        customer, platform = Mock(), Mock()
        customer.resolve.side_effect = _fake_dns({("example.com", "A"): [PLATFORM_V4]})
        platform.resolve.side_effect = _fake_dns({("freepod.eu", "A"): [PLATFORM_V4]})
        with patch(
            "app.services.hostnames._authoritative_resolver",
            side_effect=lambda name: platform if name == "freepod.eu" else customer,
        ), patch("app.services.hostnames.dns.resolver.resolve") as module_resolve:
            _check_dns_target("example.com", _settings(domain="freepod.eu"))
        module_resolve.assert_not_called()
        assert {c.args[0] for c in platform.resolve.call_args_list} == {"freepod.eu"}


# ── Orchestration (short-circuit behavior) ────────────────────────────


class TestRequireValidHostname:
    def test_valid_hostname_returns_it(self, db_session):
        result = require_valid_hostname_for_deployment(
            db_session, "valid.example.com", handle=None, settings=_settings(),
        )
        assert result == "valid.example.com"

    def test_short_circuits_on_format(self, db_session):
        """Format failure should not touch the DB or DNS."""
        with pytest.raises(HostnameException) as exc_info:
            require_valid_hostname_for_deployment(
                db_session, "-invalid", handle=None, settings=_settings(domain="freepod.eu"),
            )
        assert exc_info.value.reason == "invalid"

    def test_mixed_case_detected_as_in_use(self, db_session, seed_parents):
        """Mixed-case FQDN should be detected as in-use when lowercase variant exists."""
        dep = make_deployment_with_release(
            db_session,
            user_id=seed_parents["user_id"],
            desired_template_id=seed_parents["template_id"],
            hostname="taken.example.com",
            status=DEPLOYMENT_STATUS_PROVISIONING,
            name="test-name-case",
            namespace="test-namespace-case",
        )
        db_session.flush()
        with pytest.raises(HostnameException) as exc_info:
            require_valid_hostname_for_deployment(
                db_session, "Taken.Example.COM",
                handle=None,
                settings=_settings(),
            )
        assert exc_info.value.reason == "in_use"

    def test_short_circuits_on_in_use(self, db_session, seed_parents):
        """In-use failure should not perform DNS resolution."""
        dep = make_deployment_with_release(
            db_session,
            user_id=seed_parents["user_id"],
            desired_template_id=seed_parents["template_id"],
            hostname="taken.example.com",
            status=DEPLOYMENT_STATUS_PROVISIONING,
            name="test-name-3",
            namespace="test-namespace-3",
        )
        db_session.flush()
        with pytest.raises(HostnameException) as exc_info:
            require_valid_hostname_for_deployment(
                db_session, "taken.example.com",
                handle=None,
                settings=_settings(domain="freepod.eu"),
            )
        assert exc_info.value.reason == "in_use"


# ── API endpoint tests ────────────────────────────────────────────────


class TestHostnameCheckEndpoint:
    def test_usable_hostname(self, client):
        resp = client.get("/api/hostnames/myapp.example.com")
        assert resp.status_code == 200
        data = resp.json()
        assert data["fqdn"] == "myapp.example.com"
        assert data["usable"] is True
        assert data["reason"] is None

    def test_invalid_format(self, client):
        resp = client.get("/api/hostnames/-bad..host")
        assert resp.status_code == 200
        data = resp.json()
        assert data["fqdn"] == "-bad..host"
        assert data["usable"] is False
        assert data["reason"] == "invalid"

    def test_name_under_a_platform_domain(self, client, monkeypatch):
        monkeypatch.setattr(
            "app.services.hostnames.get_settings",
            lambda: _settings(platform_domains=["freepod.eu"]),
        )
        resp = client.get("/api/hostnames/smtp.freepod.eu")
        assert resp.status_code == 200
        assert resp.json()["usable"] is False
        assert resp.json()["reason"] == "reserved"

    def test_hostname_in_use(self, client, db_session):
        # Create a product, template, and deployment to occupy the hostname
        product = client.post("/api/products", json={"name": "hn-test", "description": "test"})
        product_id = product.json()["id"]
        template = client.post(
            f"/api/products/{product_id}/templates",
            json={
                "chart_ref": "oci://example/chart",
                "chart_version": "1.0.0",
                "values_schema_json": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "host": {"type": "string", "title": "hostname"},
                    },
                },
            },
        )
        template_id = template.json()["id"]
        # Make it the canonical template
        client.put(f"/api/products/{product_id}", json={"template_id": template_id})
        ptv_id = create_free_plan_template(db_session, product_id)
        user_id = create_user(client, "hn-test@example.com")["id"]
        client.post(
            f"/api/users/{user_id}/deployments",
            json={
                "desired_template_id": template_id,
                "user_values_json": {"host": "occupied.example.com"},
                "plan_template_id": ptv_id,
            },
        )
        resp = client.get("/api/hostnames/occupied.example.com")
        assert resp.status_code == 200
        assert resp.json()["usable"] is False
        assert resp.json()["reason"] == "in_use"

    def test_not_resolving(self, client, monkeypatch):
        monkeypatch.setattr(
            "app.services.hostnames.get_settings",
            lambda: _settings(domain="freepod.eu"),
        )
        with patch(
            "app.services.hostnames._authoritative_resolver", return_value=None
        ), patch(
            "app.services.hostnames.dns.resolver.resolve",
            side_effect=dns.resolver.NXDOMAIN("nope"),
        ):
            resp = client.get("/api/hostnames/nxdomain.example.com")
        assert resp.status_code == 200
        assert resp.json()["usable"] is False
        assert resp.json()["reason"] == "not_resolving"

    def test_auth_required(self, db_session):
        """Whether a name is usable depends on whose handle it ends in, so the
        check is not public."""
        def override_get_db():
            yield db_session

        fastapi_app.dependency_overrides[get_session] = override_get_db
        with TestClient(fastapi_app) as no_auth_client:
            resp = no_auth_client.get("/api/hostnames/test.example.com")
            assert resp.status_code == 404
        fastapi_app.dependency_overrides.clear()

    def test_mixed_case_fqdn_normalized_in_response(self, client):
        resp = client.get("/api/hostnames/MyApp.Example.COM")
        assert resp.status_code == 200
        data = resp.json()
        assert data["fqdn"] == "myapp.example.com"

    def test_response_has_exactly_three_fields(self, client):
        resp = client.get("/api/hostnames/clean.example.com")
        assert resp.status_code == 200
        assert set(resp.json().keys()) == {"fqdn", "usable", "reason"}


# ── CNAME target endpoint tests ───────────────────────────────────────


class TestCnameTargetEndpoint:
    def test_returns_configured_domain(self, client, monkeypatch):
        monkeypatch.setattr(
            "app.api.hostnames.get_settings",
            lambda: _settings(domain="dev.freepod.eu"),
        )
        resp = client.get("/api/cname-target")
        assert resp.status_code == 200
        assert resp.json() == "dev.freepod.eu"

    def test_advertises_the_tenant_domain(self, client, monkeypatch):
        monkeypatch.setattr(
            "app.api.hostnames.get_settings",
            lambda: _settings(domain="dev.freepod.eu", tenant_domain="dev.freepod.app"),
        )
        assert client.get("/api/cname-target").json() == "dev.freepod.app"

    def test_returns_empty_string_when_unconfigured(self, client, monkeypatch):
        monkeypatch.setattr(
            "app.api.hostnames.get_settings",
            lambda: _settings(domain=""),
        )
        resp = client.get("/api/cname-target")
        assert resp.status_code == 200
        assert resp.json() == ""

    def test_no_auth_required(self, db_session):
        def override_get_db():
            yield db_session

        fastapi_app.dependency_overrides[get_session] = override_get_db
        with TestClient(fastapi_app) as no_auth_client:
            resp = no_auth_client.get("/api/cname-target")
            assert resp.status_code == 200
        fastapi_app.dependency_overrides.clear()


# ── Server-side hostname enforcement tests ────────────────────────────


class TestServerSideEnforcement:
    def test_create_deployment_rejects_reserved_hostname(self, client, db_session, monkeypatch):
        monkeypatch.setattr(
            "app.services.hostnames.get_settings",
            lambda: _settings(platform_domains=["example.com"]),
        )
        product = client.post("/api/products", json={"name": "enforce-prod", "description": "test"})
        product_id = product.json()["id"]
        template = client.post(
            f"/api/products/{product_id}/templates",
            json={
                "chart_ref": "oci://example/chart",
                "chart_version": "1.0.0",
                "values_schema_json": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"host": {"type": "string", "title": "hostname"}},
                },
            },
        )
        template_id = template.json()["id"]
        # Make it the canonical template
        client.put(f"/api/products/{product_id}", json={"template_id": template_id})
        ptv_id = create_free_plan_template(db_session, product_id)
        user_id = create_user(client, "enforce@example.com")["id"]

        resp = client.post(
            f"/api/users/{user_id}/deployments",
            json={
                "desired_template_id": template_id,
                "user_values_json": {"host": "reserved.example.com"},
                "plan_template_id": ptv_id,
            },
        )
        assert resp.status_code == 409
        assert "reserved" in resp.json()["detail"]

    def test_create_deployment_rejects_in_use_hostname(self, client, db_session):
        product = client.post("/api/products", json={"name": "enforce-inuse", "description": "test"})
        product_id = product.json()["id"]
        template = client.post(
            f"/api/products/{product_id}/templates",
            json={
                "chart_ref": "oci://example/chart",
                "chart_version": "1.0.0",
                "values_schema_json": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"host": {"type": "string", "title": "hostname"}},
                },
            },
        )
        template_id = template.json()["id"]
        # Make it the canonical template
        client.put(f"/api/products/{product_id}", json={"template_id": template_id})
        ptv_id = create_free_plan_template(db_session, product_id)
        user_id = create_user(client, "enforce-inuse@example.com")["id"]

        # First deployment succeeds
        resp1 = client.post(
            f"/api/users/{user_id}/deployments",
            json={
                "desired_template_id": template_id,
                "user_values_json": {"host": "taken.enforce.example.com"},
                "plan_template_id": ptv_id,
            },
        )
        assert resp1.status_code == 201

        # Second deployment with same hostname is rejected
        user2_id = create_user(client, "enforce-inuse2@example.com")["id"]
        resp2 = client.post(
            f"/api/users/{user2_id}/deployments",
            json={
                "desired_template_id": template_id,
                "user_values_json": {"host": "taken.enforce.example.com"},
                "plan_template_id": ptv_id,
            },
        )
        assert resp2.status_code == 409
        assert "in_use" in resp2.json()["detail"]

    def test_create_deployment_skips_validation_when_no_hostname(self, client, db_session):
        """Templates without a hostname-titled field should not trigger validation."""
        product = client.post("/api/products", json={"name": "enforce-nohost", "description": "test"})
        product_id = product.json()["id"]
        template = client.post(
            f"/api/products/{product_id}/templates",
            json={
                "chart_ref": "oci://example/chart",
                "chart_version": "1.0.0",
                "values_schema_json": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"message": {"type": "string"}},
                },
            },
        )
        template_id = template.json()["id"]
        # Make it the canonical template
        client.put(f"/api/products/{product_id}", json={"template_id": template_id})
        ptv_id = create_free_plan_template(db_session, product_id)
        user_id = create_user(client, "enforce-nohost@example.com")["id"]

        resp = client.post(
            f"/api/users/{user_id}/deployments",
            json={
                "desired_template_id": template_id,
                "user_values_json": {"message": "hello"},
                "plan_template_id": ptv_id,
            },
        )
        assert resp.status_code == 201
        assert resp.json()["deployment"]["hostname"] is None

    def test_update_deployment_allows_same_hostname(self, client, db_session):
        """Updating a deployment should not reject its own current hostname."""
        product = client.post("/api/products", json={"name": "enforce-update", "description": "test"})
        product_id = product.json()["id"]
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {"host": {"type": "string", "title": "hostname"}},
        }
        tmpl1 = client.post(
            f"/api/products/{product_id}/templates",
            json={"chart_ref": "oci://example/chart", "chart_version": "1.0.0", "values_schema_json": schema},
        )
        # Make it the canonical template
        client.put(f"/api/products/{product_id}", json={"template_id": tmpl1.json()["id"]})
        tmpl2 = client.post(
            f"/api/products/{product_id}/templates",
            json={"chart_ref": "oci://example/chart", "chart_version": "2.0.0", "values_schema_json": schema},
        )
        user_id = create_user(client, "enforce-update@example.com")["id"]

        ptv_id = create_free_plan_template(db_session, product_id)

        dep = client.post(
            f"/api/users/{user_id}/deployments",
            json={"desired_template_id": tmpl1.json()["id"], "user_values_json": {"host": "same.example.com"}, "plan_template_id": ptv_id},
        )
        assert dep.status_code == 201
        dep_id = dep.json()["deployment"]["id"]

        # Mark create job done and set status to ready so update is allowed
        create_job = db_session.exec(
            select(DeploymentReconcileJobORM).where(
                DeploymentReconcileJobORM.deployment_id == UUID(dep_id),
                DeploymentReconcileJobORM.reason == "create",
            )
        ).one()
        JobService(db_session).mark_job_done(job_id=create_job.id)
        from app.models import DeploymentORM
        dep_orm = db_session.get(DeploymentORM, UUID(dep_id))
        dep_orm.status = "ready"
        db_session.add(dep_orm)
        db_session.commit()

        # Upgrade template but keep same hostname — should succeed
        resp = client.put(
            f"/api/users/{user_id}/deployments/{dep_id}",
            json={"desired_template_id": tmpl2.json()["id"], "user_values_json": {"host": "same.example.com"}},
        )
        assert resp.status_code == 200
        assert resp.json()["hostname"] == "same.example.com"
