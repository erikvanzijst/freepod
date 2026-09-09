"""The certificate an account holds.

One wildcard per account rather than one per deployment, in a platform
namespace, never deleted — see openspec/specs/account-tls-certificate/spec.md.
"""

from __future__ import annotations

import pytest
from app.config import CaelusSettings
from app.provisioner import Provisioner

TLS_NAMESPACE = "caelus-tls"


class RecordingKube:
    def __init__(self) -> None:
        self.manifests: list[dict] = []

    def apply_manifest(self, manifest, *, error_message: str) -> None:
        self.manifests.append(manifest)


@pytest.fixture
def kube(monkeypatch):
    recorder = RecordingKube()
    monkeypatch.setattr(
        "app.provisioner.get_settings",
        lambda: CaelusSettings(
            tls_namespace=TLS_NAMESPACE,
            account_tls_cluster_issuer="letsencrypt-dns",
            _env_file=None,
        ),
    )
    return recorder


@pytest.fixture
def provisioner(kube):
    return Provisioner(kube=kube)


def test_the_certificate_covers_every_application_hostname(provisioner, kube):
    provisioner.ensure_account_certificate(fqdn="erik.dev.freepod.eu")

    spec = kube.manifests[0]["spec"]
    assert spec["dnsNames"] == ["*.erik.dev.freepod.eu", "erik.dev.freepod.eu"]


def test_the_key_is_elliptic_curve_and_stated_explicitly(provisioner, kube):
    """The issuer client's default is RSA, which costs parse time on every
    ingress rebuild and three times the secret size."""
    provisioner.ensure_account_certificate(fqdn="erik.dev.freepod.eu")

    assert kube.manifests[0]["spec"]["privateKey"] == {"algorithm": "ECDSA", "size": 256}


def test_it_lives_in_the_platform_namespace_and_no_tenants(provisioner, kube):
    provisioner.ensure_account_certificate(fqdn="erik.dev.freepod.eu")

    assert kube.manifests[0]["metadata"]["namespace"] == TLS_NAMESPACE


def test_it_is_issued_through_the_dns_01_issuer(provisioner, kube):
    provisioner.ensure_account_certificate(fqdn="erik.dev.freepod.eu")

    assert kube.manifests[0]["spec"]["issuerRef"] == {
        "name": "letsencrypt-dns",
        "kind": "ClusterIssuer",
    }


def test_the_secret_carries_the_label_membership_is_derived_from(provisioner, kube):
    """On secretTemplate, because cert-manager does not copy a certificate's own
    labels onto the secret it writes — and the secret is what is listed."""
    provisioner.ensure_account_certificate(fqdn="erik.dev.freepod.eu")

    spec = kube.manifests[0]["spec"]
    assert spec["secretTemplate"]["labels"] == {"caelus.dev/component": "account-tls"}


def test_names_carry_the_environment(provisioner, kube):
    """dev and production share the one namespace, and `erik` is a different
    person in each."""
    dev = provisioner.ensure_account_certificate(fqdn="erik.dev.freepod.eu")
    prod = provisioner.ensure_account_certificate(fqdn="erik.freepod.eu")

    assert dev == "acct-erik-dev-freepod-eu"
    assert prod == "acct-erik-freepod-eu"
    assert dev != prod


def test_the_secret_name_matches_the_certificate_name(provisioner, kube):
    returned = provisioner.ensure_account_certificate(fqdn="erik.dev.freepod.eu")

    manifest = kube.manifests[0]
    assert manifest["metadata"]["name"] == returned
    assert manifest["spec"]["secretName"] == returned


def test_a_repeat_call_rewrites_the_same_object(provisioner, kube):
    """A stable name is what keeps a reconcile from churning the certificate,
    and churn is what spends the weekly allowance."""
    first = provisioner.ensure_account_certificate(fqdn="erik.dev.freepod.eu")
    second = provisioner.ensure_account_certificate(fqdn="erik.dev.freepod.eu")

    assert first == second
    assert kube.manifests[0] == kube.manifests[1]
