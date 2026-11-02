resource "kubernetes_secret" "keycloak" {
  metadata {
    name      = "keycloak-db-secret"
    namespace = var.namespace
  }

  type = "Opaque"

  data = {
    # TLS terminates at Traefik: Keycloak serves plain HTTP and trusts the
    # X-Forwarded-* headers Traefik sets. Traefik is the only path in, but any
    # pod reaching the ClusterIP directly could forge a client IP. Harmless
    # while bruteForceProtected is off; revisit if it is ever enabled, since
    # IP-based lockout would become spoofable.
    KC_PROXY_HEADERS = "xforwarded"
    KC_HTTP_ENABLED  = "true"

    # Pins every URL Keycloak generates, and the issuer, to the public URL,
    # however a request reached it. Every client, in-cluster ones included,
    # talks to Keycloak through that URL.
    KC_HOSTNAME = "https://keycloak.${var.domain}"

    # Serves /health/* on the management port (9000) for the probes below.
    KC_HEALTH_ENABLED = "true"

    # INFO, not DEBUG: at DEBUG a near-idle Keycloak emitted ~32k lines in six
    # minutes (99.9% of the log), which is pure disk and Loki ingest on a node
    # with a history of disk pressure. Raise it temporarily when debugging.
    KC_LOG_LEVEL   = "INFO"
    KC_DB          = "postgres"
    KC_DB_URL      = "jdbc:postgresql://${kubernetes_service.postgres.metadata[0].name}.${var.namespace}.svc.cluster.local:5432/keycloak"
    KC_DB_USERNAME = "keycloak"
    KC_DB_PASSWORD = "keycloak"

    # Creates the master-realm admin on an empty database only; ignored once
    # it exists.
    KC_BOOTSTRAP_ADMIN_USERNAME = "admin"
    KC_BOOTSTRAP_ADMIN_PASSWORD = var.keycloak_admin_password
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

    # A new version migrates the schema on startup, one-way, so the old pod
    # must be gone before the new one starts.
    strategy {
      type = "Recreate"
    }

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

          args = ["start"]

          port {
            container_port = 8080
          }

          port {
            name           = "management"
            container_port = 9000
          }

          # The HTTP port opens before bootstrap (and any schema migration)
          # has finished, so traffic waits for /health/ready. Startup gets up
          # to 10 minutes before liveness takes over.
          startup_probe {
            http_get {
              path = "/health/started"
              port = "management"
            }
            period_seconds    = 10
            failure_threshold = 60
          }

          readiness_probe {
            http_get {
              path = "/health/ready"
              port = "management"
            }
            period_seconds = 10
          }

          liveness_probe {
            http_get {
              path = "/health/live"
              port = "management"
            }
            period_seconds    = 30
            failure_threshold = 3
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
