# The builds namespace's own resources: the identity build pods run as, and
# the network jail they run inside.

# Build pods run as this ServiceAccount and it is granted nothing — no Role, no
# RoleBinding, anywhere. That is the point: the pod executes tenant-supplied
# build commands, so any permission here would be a permission handed to every
# tenant.
#
# `automount_service_account_token = false` is what makes it real: without it
# the pod would still receive a mounted token for this account, and a token is
# a credential even when the account it names can do nothing today.
resource "kubernetes_service_account" "builder" {
  metadata {
    name      = "caelus-builder"
    namespace = var.builds_namespace

    labels = {
      "app.kubernetes.io/managed-by" = "terraform"
      "app.kubernetes.io/component"  = "builder"
    }
  }

  automount_service_account_token = false
}

# Default-deny both directions, then open exactly what a build needs.
#
# Shaped after the tenant baseline policy in api/app/network_policy.py, with
# two deliberate differences, because concurrent
# builds belonging to *different tenants* share this namespace:
#
#   1. There is no ingress allowance at all. Nothing should ever connect to a
#      build pod: the worker collects output through the Kubernetes API and the
#      result through the pod's termination message, neither of which is a
#      connection to the pod.
#   2. There is no intra-namespace egress rule. The tenant policy has
#      `{"to": [{"podSelector": {}}]}` to let a tenant's own pods talk to each
#      other; copying it here would let one tenant's build reach another's,
#      which is the single thing this namespace's shared occupancy makes
#      possible. Do not "restore" it for symmetry with the tenant policy.
#
# Together with `automountServiceAccountToken: false` these are what make a
# shared builds namespace safe: verified by probe, a build pod cannot reach
# another build pod, the API server, Postgres, or the Caelus API.
#
# The `except` list is what does most of the work. Denying the RFC1918 ranges
# and link-local in one rule blocks, without naming any of them:
#
#   - Postgres and every other platform service (ClusterIPs in 10.43.0.0/16),
#   - the Kubernetes API server (10.43.0.1),
#   - every tenant workload (pod CIDR 10.42.0.0/16),
#   - both environments' `caelus` namespaces, including the other one's,
#   - the node and the rest of the LAN,
#   - cloud/link-local metadata endpoints (169.254.0.0/16).
#
# Only the internal registry then needs a hole punched through it.
resource "kubernetes_network_policy" "builds" {
  metadata {
    name      = "caelus-build-baseline"
    namespace = var.builds_namespace

    labels = {
      "app.kubernetes.io/managed-by" = "terraform"
    }
  }

  spec {
    pod_selector {}
    policy_types = ["Ingress", "Egress"]

    # No ingress rules: nothing reaches a build pod. The worker collects its
    # output through the Kubernetes API and its result through the pod's
    # termination message, neither of which is a connection to the pod.

    # DNS, to kube-dns pods (matches after the ClusterIP is DNAT'd).
    egress {
      to {
        namespace_selector {
          match_labels = {
            "kubernetes.io/metadata.name" = "kube-system"
          }
        }
        pod_selector {
          match_labels = {
            "k8s-app" = "kube-dns"
          }
        }
      }
      ports {
        port     = "53"
        protocol = "UDP"
      }
      ports {
        port     = "53"
        protocol = "TCP"
      }
    }

    # DNS, to the ClusterIP itself — belt and braces for the pre-DNAT match,
    # mirroring the tenant policy.
    egress {
      to {
        ip_block {
          cidr = "${var.dns_cluster_ip}/32"
        }
      }
      ports {
        port     = "53"
        protocol = "UDP"
      }
      ports {
        port     = "53"
        protocol = "TCP"
      }
    }

    # This environment's tenant registry (authenticated-tenant-registry D18).
    # The pod on its container port is what the policy sees once the
    # Service's ClusterIP is DNAT'd; the ClusterIP itself is the pre-DNAT
    # match, as for DNS above.
    egress {
      to {
        namespace_selector {
          match_labels = {
            "kubernetes.io/metadata.name" = var.registry_namespace
          }
        }
        pod_selector {
          match_labels = var.registry_pod_labels
        }
      }
      ports {
        port     = "5000"
        protocol = "TCP"
      }
    }

    egress {
      to {
        ip_block {
          cidr = "${var.registry_cluster_ip}/32"
        }
      }
      ports {
        port     = "443"
        protocol = "TCP"
      }
    }

    # The public internet, minus every internal range. This covers dependency
    # fetching (npm, PyPI, crates.io …), pulling the pinned Railpack frontend
    # from ghcr.io, and — because it resolves to the homelab's *public* address
    # even from inside the cluster — retrieving the artifact from Garage at
    # blob.freepod.eu.
    egress {
      to {
        ip_block {
          cidr = "0.0.0.0/0"
          except = [
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
            "169.254.0.0/16",
          ]
        }
      }
    }
  }
}
