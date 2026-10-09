# app-auth: "Sign in with Freepod" for tenant apps. One process, two listeners:
#
#   :8080  the verifier, reached only in-cluster by Traefik's forward-auth from
#          every auth-enabled custom deployment (chart: app-auth middleware);
#   :8081  the broker, the only listener exposed, on login.<domain>.
#
# See daemons/app-auth/README.md and the app-authentication design doc.

locals {
  labels = { app = "app-auth" }
}

# The session keyring. Every key seals the same way; the first seals, all open.
# Rotating: add a new key in FRONT of this one (id k2), apply, and drop k1 once
# sessions sealed with it have expired (7 days). Replacing k1 outright signs
# everyone out of every app.
resource "random_bytes" "session_key_k1" {
  length = 32
}

resource "kubernetes_secret" "app_auth" {
  metadata {
    name      = "app-auth"
    namespace = var.namespace
  }

  data = {
    APP_AUTH_DATABASE_URL       = var.database_url
    APP_AUTH_SESSION_KEYS       = "k1:${random_bytes.session_key_k1.base64}"
    APP_AUTH_OIDC_CLIENT_SECRET = var.oidc_client_secret
  }
}

resource "kubernetes_deployment" "app_auth" {
  metadata {
    name      = "app-auth"
    namespace = var.namespace
    labels    = local.labels
  }

  spec {
    replicas = 1

    selector {
      match_labels = local.labels
    }

    template {
      metadata {
        labels = local.labels
        annotations = {
          "checksum/secret" = sha256(jsonencode(kubernetes_secret.app_auth.data))
        }
      }

      spec {
        automount_service_account_token = false

        security_context {
          run_as_non_root = true
          run_as_user     = 65534
          seccomp_profile {
            type = "RuntimeDefault"
          }
        }

        container {
          name    = "app-auth"
          image   = var.image
          command = ["/app-auth"]

          port {
            name           = "verify"
            container_port = 8080
          }

          port {
            name           = "broker"
            container_port = 8081
          }

          env {
            name  = "APP_AUTH_LOGIN_URL"
            value = "https://login.${var.domain}"
          }

          env {
            name  = "APP_AUTH_OIDC_ISSUER"
            value = var.oidc_issuer
          }

          env {
            name  = "APP_AUTH_OIDC_CLIENT_ID"
            value = var.oidc_client_id
          }

          env_from {
            secret_ref {
              name = kubernetes_secret.app_auth.metadata[0].name
            }
          }

          # Readiness only, on the process: sessions are checked without the
          # database, so a database outage must not pull the pods out of
          # service. No liveness probe, for the ssh resolver's reason --
          # restarting fixes no dependency outage.
          readiness_probe {
            http_get {
              path = "/healthz"
              port = "verify"
            }
            period_seconds = 5
          }

          security_context {
            allow_privilege_escalation = false
            read_only_root_filesystem  = true
            capabilities {
              drop = ["ALL"]
            }
          }

          resources {
            requests = {
              cpu    = "10m"
              memory = "16Mi"
            }
            limits = {
              memory = "128Mi"
            }
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      spec[0].template[0].metadata[0].annotations["kubectl.kubernetes.io/restartedAt"],
    ]
  }
}

resource "kubernetes_service" "app_auth" {
  metadata {
    name      = "app-auth"
    namespace = var.namespace
  }

  spec {
    selector = local.labels

    port {
      name        = "verify"
      port        = 8080
      target_port = "verify"
    }

    port {
      name        = "broker"
      port        = 8081
      target_port = "broker"
    }
  }
}

# Only the broker is public. The verifier's port is reachable in-cluster alone:
# nothing routes to it, and it is not in this route.
resource "kubernetes_manifest" "broker_route" {
  manifest = {
    apiVersion = "traefik.io/v1alpha1"
    kind       = "IngressRoute"
    metadata = {
      name      = "app-auth-broker"
      namespace = var.namespace
    }
    spec = {
      entryPoints = ["web", "websecure"]
      routes = [{
        match = "Host(`login.${var.domain}`)"
        kind  = "Rule"
        services = [{
          name = kubernetes_service.app_auth.metadata[0].name
          port = 8081
        }]
      }]
    }
  }
}
