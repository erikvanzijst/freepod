resource "kubernetes_secret" "keycloak" {
  metadata {
    name      = "keycloak-db-secret"
    namespace = var.namespace
  }

  type = "Opaque"

  data = {
    # Replaces the deprecated `KC_PROXY=edge`, which Keycloak 24 warns about
    # and later versions remove. `edge` bundled TWO concerns, and both need a
    # replacement — dropping it while setting only proxy-headers makes
    # Keycloak refuse to start with "Key material not provided to setup
    # HTTPS", because production mode then expects to terminate TLS itself:
    #
    #   1. parse the X-Forwarded-* headers          -> KC_PROXY_HEADERS
    #   2. TLS terminates at the proxy, serve HTTP  -> KC_HTTP_ENABLED
    #
    # KC_HOSTNAME_URL below is a third, separate thing: it pins the URLs
    # Keycloak *generates* to https, and does not affect the listener.
    KC_PROXY_HEADERS = "xforwarded"
    KC_HTTP_ENABLED  = "true"

    # Redundant alongside proxy-headers (which turns on Quarkus' forwarded
    # address handling itself), kept only because dropping it is an unrelated
    # change. It is what the "X-Forwarded-* headers will be considered"
    # startup warning refers to: Traefik is the only path in, but any pod
    # reaching the ClusterIP directly could forge a client IP. Harmless while
    # bruteForceProtected is off; revisit if it is ever enabled, since
    # IP-based lockout would become spoofable.
    KC_PROXY_ADDRESS_FORWARDING    = "true"
    KC_HOSTNAME_STRICT             = "false"
    KC_HOSTNAME_STRICT_BACKCHANNEL = "false"
    KC_HOSTNAME_URL                = "https://keycloak.${var.domain}"
    KC_HOSTNAME_ADMIN_URL          = "https://keycloak.${var.domain}"

    # INFO, not DEBUG: at DEBUG a near-idle Keycloak emitted ~32k lines in six
    # minutes (99.9% of the log), which is pure disk and Loki ingest on a node
    # with a history of disk pressure. Raise it temporarily when debugging.
    KC_LOG_LEVEL            = "INFO"
    KC_DB                   = "postgres"
    KC_DB_URL               = "jdbc:postgresql://${kubernetes_service.postgres.metadata[0].name}.${var.namespace}.svc.cluster.local:5432/keycloak"
    KC_DB_USERNAME          = "keycloak"
    KC_DB_PASSWORD          = "keycloak"
    KEYCLOAK_ADMIN          = "admin"
    KEYCLOAK_ADMIN_PASSWORD = var.keycloak_admin_password
  }
}

resource "kubernetes_deployment" "keycloak" {
  metadata {
    name      = "keycloak"
    namespace = var.namespace
    labels = {
      app = "keycloak"
    }
  }

  spec {
    replicas = 1

    selector {
      match_labels = {
        app = "keycloak"
      }
    }

    template {
      metadata {
        labels = {
          app = "keycloak"
        }
      }

      spec {
        container {
          name  = "keycloak"
          image = var.keycloak_image

          image_pull_policy = "Always"

          args = ["start", "--hostname-debug=true"]

          port {
            container_port = 8080
          }

          env_from {
            secret_ref {
              name = kubernetes_secret.keycloak.metadata[0].name
            }
          }
        }
      }
    }
  }
  # Ignore restartedAt annotations written by `kubectl rollout restart`
  lifecycle {
    ignore_changes = [
      spec[0].template[0].metadata[0].annotations["kubectl.kubernetes.io/restartedAt"],
    ]
  }
}

resource "kubernetes_service" "keycloak" {
  metadata {
    name      = "keycloak"
    namespace = var.namespace
  }

  spec {
    selector = {
      app = "keycloak"
    }

    port {
      port        = 80
      target_port = 8080
    }
  }
}
