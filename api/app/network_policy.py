from __future__ import annotations

import re
from typing import Any

from app.config import CaelusSettings

# Namespace labels that make the NetworkPolicy jail non-bypassable and mark the
# namespace as a Caelus tenant. Pod Security Admission ``baseline`` forbids the
# hostNetwork / hostPort / hostPath / privileged escapes that would otherwise let
# a pod sidestep pod-network filtering entirely (a hostNetwork pod uses the node's
# network namespace, which NetworkPolicy never sees). ``caelus.dev/tenant`` lets
# shared services and cluster-wide policy select tenant namespaces.
TENANT_NAMESPACE_LABELS: dict[str, str] = {
    "caelus.dev/tenant": "true",
    "pod-security.kubernetes.io/enforce": "baseline",
    "pod-security.kubernetes.io/enforce-version": "latest",
}


def _label_value(raw: str | None) -> str | None:
    """``raw`` as a valid Kubernetes label value, or ``None`` if nothing survives."""
    if raw is None:
        return None
    value = re.sub(r"[^a-z0-9._-]", "-", str(raw).strip().lower())[:63]
    value = value.strip("-_.")
    return value or None


def deployment_namespace_labels(
    *, owner_id: int | None, product: str | None, environment: str | None
) -> dict[str, str]:
    """``TENANT_NAMESPACE_LABELS`` plus the identity metrics aggregate on.

    kube-state-metrics exposes these as ``kube_namespace_labels`` dimensions, so
    dashboards can group by owner or product. ``environment`` belongs here
    because both environments share a cluster while ``user.id`` is per-database:
    without it, owner 5 in dev and owner 5 in prod sum together.
    """
    labels = dict(TENANT_NAMESPACE_LABELS)
    for key, raw in (
        ("caelus.dev/owner-id", owner_id),
        ("caelus.dev/product", product),
        ("caelus.dev/environment", environment),
    ):
        value = _label_value(raw)
        if value is not None:
            labels[key] = value
    return labels


def build_tenant_baseline_policy(*, namespace: str, settings: CaelusSettings) -> dict[str, Any]:
    """Render the platform-owned baseline NetworkPolicy for a tenant namespace.

    Default-deny in both directions (``podSelector: {}`` + both policy types),
    then allow exactly:

    - ingress from the shared Traefik edge (any port, so per-chart service ports
      never need standardizing), from this environment's SFTP router (sshpiper,
      sidecar port only -- it has no business on app ports, and the port scoping
      is also what keeps the other environment's router out), plus free traffic
      within the namespace;
    - egress: free traffic within the namespace, DNS, the shared SMTP relay, the
      shared database pooler (client port only), and the public internet minus
      every internal range (LAN, node, other tenants, the service CIDR, and
      link-local/cloud-metadata).

    The tenant PostgreSQL server is deliberately not among the allowances: it
    sits behind the same internal ranges the internet rule excludes, so the
    pooler is the only route to a database, and the pooler is therefore
    unbypassable rather than merely conventional.

    The policy is byte-for-byte identical for every tenant; only
    ``metadata.namespace`` varies. That is what lets a single definition, applied
    per namespace, cover the whole fleet -- and why a fleet-wide update is just a
    re-apply of this render (see ``caelus sync-network-policies``).
    """
    dns_ports = [
        {"port": 53, "protocol": "UDP"},
        {"port": 53, "protocol": "TCP"},
    ]
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {
            "name": settings.tenant_netpol_name,
            "namespace": namespace,
            "labels": {"app.kubernetes.io/managed-by": "caelus"},
        },
        "spec": {
            "podSelector": {},
            "policyTypes": ["Ingress", "Egress"],
            "ingress": [
                {  # shared Traefik edge -> any pod, any port
                    "from": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {
                                    "kubernetes.io/metadata.name": settings.ingress_namespace
                                }
                            },
                            "podSelector": {
                                "matchLabels": {"app.kubernetes.io/name": settings.ingress_pod_label}
                            },
                        }
                    ]
                },
                {  # this environment's SFTP router -> sidecar port only
                    "from": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {
                                    "kubernetes.io/metadata.name": settings.sshpiper_namespace
                                }
                            },
                            "podSelector": {
                                "matchLabels": {"app": settings.sshpiper_pod_label}
                            },
                        }
                    ],
                    "ports": [{"port": settings.sftp_sidecar_port, "protocol": "TCP"}],
                },
                {"from": [{"podSelector": {}}]},  # free traffic within the namespace
            ],
            "egress": [
                {"to": [{"podSelector": {}}]},  # free traffic within the namespace
                {  # DNS to kube-dns pods (post-DNAT match)
                    "to": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {"kubernetes.io/metadata.name": "kube-system"}
                            },
                            "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}},
                        }
                    ],
                    "ports": dns_ports,
                },
                {  # DNS ClusterIP (pre-DNAT belt & suspenders)
                    "to": [{"ipBlock": {"cidr": f"{settings.dns_cluster_ip}/32"}}],
                    "ports": dns_ports,
                },
                {  # shared SMTP relay
                    "to": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {"kubernetes.io/metadata.name": settings.mailer_namespace}
                            },
                            "podSelector": {"matchLabels": {"app": settings.mailer_pod_label}},
                        }
                    ],
                    "ports": [{"port": settings.mailer_port, "protocol": "TCP"}],
                },
                {  # shared database pooler -> its client port only
                    "to": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {
                                    "kubernetes.io/metadata.name": settings.tenant_db_pooler_namespace
                                }
                            },
                            "podSelector": {
                                "matchLabels": {"app": settings.tenant_db_pooler_pod_label}
                            },
                        }
                    ],
                    "ports": [{"port": settings.tenant_db_pooler_port, "protocol": "TCP"}],
                },
                {  # internet, minus every internal range + link-local/metadata
                    "to": [
                        {
                            "ipBlock": {
                                "cidr": "0.0.0.0/0",
                                "except": list(settings.tenant_egress_except_cidrs),
                            }
                        }
                    ]
                },
            ],
        },
    }
