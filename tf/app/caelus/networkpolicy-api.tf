# Ingress jail for the platform API so it cannot be reached from any tenant
# pod, or other in-cluster component.
#
# The sole legitimate in-cluster client is Traefik. Every public route to the
# API -- the authenticated `/api` (forward-auth middleware), `/api/webhooks`,
# and `/api/registry/token` (the registry's token realm is the public URL) --
# is a Traefik Ingress, and with forward-auth Traefik itself forwards the
# request upstream, so the connection the API sees comes from the Traefik pod,
# not from oauth2-proxy. The API serves no scraped `/metrics` and defines no
# httpGet probes, so there is no kubelet- or Prometheus-sourced traffic to
# allow.
resource "kubernetes_network_policy" "api" {
  metadata {
    name      = "caelus-api-ingress"
    namespace = var.namespace

    labels = {
      "app.kubernetes.io/managed-by" = "terraform"
    }
  }

  spec {
    pod_selector {
      match_labels = {
        app = "caelus-api"
      }
    }
    policy_types = ["Ingress"]

    # Traefik (kube-system) is the only client; it reaches the API on 8000.
    ingress {
      from {
        namespace_selector {
          match_labels = {
            "kubernetes.io/metadata.name" = "kube-system"
          }
        }
        pod_selector {
          match_labels = {
            "app.kubernetes.io/name" = "traefik"
          }
        }
      }
      ports {
        port     = "8000"
        protocol = "TCP"
      }
    }
  }
}
