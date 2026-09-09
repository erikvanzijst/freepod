# The platform's TLS namespace: the certificate store Traefik serves from, the
# platform wildcard behind it, and (written at runtime by the reconciler, never
# here) every account's certificate.
#
# This module is a cluster singleton shared by dev and prod. Traefik honours one
# TLSStore named `default`, so there is no per-environment version of any of it.
resource "kubernetes_namespace" "tls" {
  metadata {
    name = var.namespace
  }
}

# Traefik's ClusterRole already grants get/list/watch on secrets cluster-wide, so
# reading this namespace needs no RBAC of its own.
resource "kubernetes_manifest" "wildcard" {
  manifest = {
    apiVersion = "cert-manager.io/v1"
    kind       = "Certificate"
    metadata = {
      name      = "wildcard-freepod-eu"
      namespace = kubernetes_namespace.tls.metadata[0].name
    }
    spec = {
      secretName = local.wildcard_secret_name

      issuerRef = {
        name = var.cluster_issuer
        kind = "ClusterIssuer"
      }

      commonName = "*.freepod.eu"
      dnsNames   = var.wildcard_dns_names
    }
  }
}

# The store lives here rather than in the Traefik release (D3), and names the
# secret without a namespace because a store's references resolve in its own
# (D2) -- which is why the wildcard's secret had to move here too.
#
# `spec.certificates` is deliberately absent. Declaring it, even as an empty
# list, would make Terraform the owner of an atomic field the reconciler must
# own, and every reconciler apply would then conflict (D4). computed_fields
# keeps the planner from reading what the reconciler wrote as drift; the two
# defaults are repeated because setting the attribute replaces them.
resource "kubernetes_manifest" "store" {
  manifest = {
    apiVersion = "traefik.io/v1alpha1"
    kind       = "TLSStore"
    metadata = {
      name      = "default"
      namespace = kubernetes_namespace.tls.metadata[0].name
    }
    spec = {
      defaultCertificate = {
        secretName = local.wildcard_secret_name
      }
    }
  }

  computed_fields = [
    "metadata.annotations",
    "metadata.labels",
    "spec.certificates",
  ]

  depends_on = [kubernetes_manifest.wildcard]
}

locals {
  wildcard_secret_name = "wildcard-freepod-eu-tls"
}
