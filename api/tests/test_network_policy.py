from __future__ import annotations

from app.config import CaelusSettings
from app.network_policy import (
    TENANT_NAMESPACE_LABELS,
    build_tenant_baseline_policy,
    tenant_network_policies,
)


def _policy(namespace: str = "tenant-abc", **overrides):
    # Every deployed environment sets the pooler namespace; the default is
    # empty, which is its own case below.
    fields = {"tenant_db_pooler_namespace": "caelus-dev", **overrides}
    settings = CaelusSettings(_env_file=None, **fields)
    return build_tenant_baseline_policy(namespace=namespace, settings=settings)


def _pooler_rule(policy):
    return next(
        r
        for r in policy["spec"]["egress"]
        if r.get("ports") == [{"port": 6432, "protocol": "TCP"}]
    )


def test_policy_is_namespaced_and_default_deny_both_directions() -> None:
    policy = _policy("tenant-abc")
    assert policy["apiVersion"] == "networking.k8s.io/v1"
    assert policy["kind"] == "NetworkPolicy"
    assert policy["metadata"]["namespace"] == "tenant-abc"
    assert policy["metadata"]["labels"]["app.kubernetes.io/managed-by"] == "caelus"
    spec = policy["spec"]
    # Empty podSelector + both policy types => default-deny, then allow-list below.
    assert spec["podSelector"] == {}
    assert set(spec["policyTypes"]) == {"Ingress", "Egress"}


def test_only_traefik_sshpiper_and_own_namespace_may_ingress() -> None:
    ingress = _policy()["spec"]["ingress"]
    traefik = ingress[0]["from"][0]
    assert traefik["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"] == "kube-system"
    assert traefik["podSelector"]["matchLabels"]["app.kubernetes.io/name"] == "traefik"
    # No port restriction on the trusted edge, so per-chart service ports don't matter.
    assert "ports" not in ingress[0]
    sshpiper = ingress[1]["from"][0]
    assert sshpiper["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"] == "sshpiper"
    assert sshpiper["podSelector"]["matchLabels"]["app"] == "sshpiper"
    # Free traffic within the namespace (multi-pod apps).
    assert ingress[2]["from"] == [{"podSelector": {}}]
    assert len(ingress) == 3


def test_sftp_router_ingress_is_port_scoped() -> None:
    # Unlike the Traefik rule, the SFTP router may only reach the sidecar port:
    # it has no business on app ports, and the scoping keeps a compromised (or
    # cross-environment) router from becoming a bridge into tenant workloads.
    sshpiper_rule = _policy()["spec"]["ingress"][1]
    assert sshpiper_rule["ports"] == [{"port": 2222, "protocol": "TCP"}]


def test_sftp_router_selector_is_environment_scoped() -> None:
    # Each environment's reconciler renders its own router namespace, so the
    # dev router never matches prod tenant policies and vice versa. This is the
    # sole enforcement layer: sshpiper's kubernetes plugin cannot filter its
    # cluster-wide Pipe watch by namespace (spike finding).
    settings = CaelusSettings(
        _env_file=None, sshpiper_namespace="sshpiper-dev", sftp_sidecar_port=2323
    )
    policy = build_tenant_baseline_policy(namespace="tenant-abc", settings=settings)
    rule = policy["spec"]["ingress"][1]
    selector = rule["from"][0]["namespaceSelector"]["matchLabels"]
    assert selector["kubernetes.io/metadata.name"] == "sshpiper-dev"
    assert rule["ports"] == [{"port": 2323, "protocol": "TCP"}]


def test_egress_allows_intra_namespace_and_dns() -> None:
    egress = _policy()["spec"]["egress"]
    assert egress[0]["to"] == [{"podSelector": {}}]  # intra-namespace

    dns_rules = [rule for rule in egress if rule.get("ports") == [
        {"port": 53, "protocol": "UDP"},
        {"port": 53, "protocol": "TCP"},
    ]]
    # Both kube-dns pod selector (post-DNAT) and the ClusterIP (pre-DNAT) are allowed.
    assert any("namespaceSelector" in rule["to"][0] for rule in dns_rules)
    assert any(rule["to"][0].get("ipBlock", {}).get("cidr") == "10.43.0.10/32" for rule in dns_rules)


def test_baseline_does_not_grant_mailer_egress() -> None:
    """The SMTP relay is no longer in the baseline: it moved to an opt-in
    overlay, so a `custom` deployment cannot reach it and spoof platform mail."""
    egress = _policy()["spec"]["egress"]
    assert all(r.get("ports") != [{"port": 25, "protocol": "TCP"}] for r in egress)


def _names(policies):
    return [p["metadata"]["name"] for p in policies]


def test_policy_set_without_mailer_is_baseline_only() -> None:
    settings = CaelusSettings(_env_file=None)
    # custom (no smtp block), no system values, and an external relay all opt out.
    for system_values in (None, {}, {"smtp": {}}, {"smtp": {"host": "smtp.sendgrid.net"}}):
        policies = tenant_network_policies(
            namespace="tenant-abc", system_values_json=system_values, settings=settings
        )
        assert _names(policies) == ["caelus-tenant-baseline"]


def test_policy_set_adds_an_egress_only_mailer_overlay_when_declared() -> None:
    settings = CaelusSettings(_env_file=None)  # mailer_namespace="mailer"
    policies = tenant_network_policies(
        namespace="tenant-abc",
        system_values_json={"smtp": {"host": "smtp.mailer.svc.cluster.local", "port": 25}},
        settings=settings,
    )
    assert _names(policies) == ["caelus-tenant-baseline", "caelus-tenant-mailer-egress"]
    overlay = policies[1]
    assert overlay["metadata"]["namespace"] == "tenant-abc"
    spec = overlay["spec"]
    assert spec["podSelector"] == {}
    assert spec["policyTypes"] == ["Egress"]  # additive: adds nothing to ingress
    rule = spec["egress"][0]
    assert rule["ports"] == [{"port": 25, "protocol": "TCP"}]
    assert rule["to"][0]["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"] == "mailer"
    assert rule["to"][0]["podSelector"]["matchLabels"]["app"] == "smtp"


def test_pooler_egress_is_namespace_pod_and_port_scoped() -> None:
    """The one route to a database. Scoped three ways so it opens nothing else:
    the platform namespace, the pooler's own pods, and its client port."""
    rule = _pooler_rule(_policy())
    to = rule["to"][0]
    assert to["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"] == "caelus-dev"
    assert to["podSelector"]["matchLabels"]["app"] == "caelus-tenant-pooler"
    assert rule["ports"] == [{"port": 6432, "protocol": "TCP"}]
    # One selector peer, so the namespace and the pod label are ANDed rather
    # than opening the whole platform namespace.
    assert len(rule["to"]) == 1


def test_postgres_itself_is_not_reachable() -> None:
    """What makes the pooler unbypassable: nothing permits 5432, and the
    server's address is inside the ranges the internet rule excludes."""
    egress = _policy()["spec"]["egress"]
    ports = [p for rule in egress for p in rule.get("ports", [])]
    assert {"port": 5432, "protocol": "TCP"} not in ports


def test_pooler_rule_is_present_for_every_tenant() -> None:
    """The policy is byte-identical fleet-wide, so the rule does not depend on
    the deployment's product having relational storage. Reachability is not
    authorization -- a deployment with no credentials cannot authenticate."""
    assert _policy("tenant-with-db") == _policy("tenant-with-db")
    a = _policy("tenant-a")
    b = _policy("tenant-b")
    a["metadata"]["namespace"] = b["metadata"]["namespace"]
    assert a == b


def test_unconfigured_pooler_yields_a_rule_that_matches_nothing() -> None:
    """An environment with no tenant cluster renders a selector matching no
    namespace, which permits no egress rather than permitting it broadly."""
    rule = _pooler_rule(_policy(tenant_db_pooler_namespace=""))
    assert rule["to"][0]["namespaceSelector"]["matchLabels"] == {
        "kubernetes.io/metadata.name": ""
    }


def test_internet_egress_excludes_all_private_ranges_and_metadata() -> None:
    egress = _policy()["spec"]["egress"]
    internet = next(r for r in egress if r["to"][0].get("ipBlock", {}).get("cidr") == "0.0.0.0/0")
    excluded = set(internet["to"][0]["ipBlock"]["except"])
    # LAN, node, other tenants/services (10/8 covers the k3s pod+service CIDRs), and
    # link-local/cloud-metadata (169.254/16 — credential-theft vector) are all denied.
    assert {"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16"} <= excluded
    assert "ports" not in internet  # all ports to the public internet


def test_tenant_labels_enforce_pod_security_baseline() -> None:
    # Pod Security Admission `baseline` is what stops a tenant from bypassing the
    # NetworkPolicy via hostNetwork; without it the netpol is theater.
    assert TENANT_NAMESPACE_LABELS["pod-security.kubernetes.io/enforce"] == "baseline"
    assert TENANT_NAMESPACE_LABELS["caelus.dev/tenant"] == "true"
