# Ingress jail for the platform API.
#
# The API authorizes on the `X-Auth-Request-Email` header that forward-auth
# injects (deps.get_current_user) and has no way to tell a header the edge set
# from one a caller forged. The only thing that makes that safe is that nothing
# but the edge can open a connection to the API: reach its ClusterIP directly
# and you are any user you name, including an admin.
#
# Until now that depended entirely on every *other* namespace's egress policy
# denying the service CIDR. That is one control, and it fails open in the window
# between a tenant pod getting its IP and k3s's policy controller programming the
# pod's rules -- a brand-new tenant pod can reach the API for a beat at startup
# and forge an admin identity. This policy closes the hole on the receiving
# side, where there is no such race: the API pod is long-lived, so its ingress
# rules are programmed long before any attacker pod is created.
#
# Ingress-only: the API's egress (database, Keycloak, Mollie, object storage)
# is deliberately left unrestricted here.
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
