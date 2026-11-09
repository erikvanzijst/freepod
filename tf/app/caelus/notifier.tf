# The notifier (daemons/notifier): delivers what platform services queue in
# notification_outbox. Its role is created by notifier-bootstrap.sql in the
# worker's init containers, after `migrate`, like app-auth's.
resource "random_password" "notifier_db" {
  length  = 32
  special = false
}

resource "kubernetes_secret" "notifier_db_bootstrap" {
  metadata {
    name      = "caelus-notifier-db-bootstrap"
    namespace = var.namespace
  }

  type = "Opaque"

  data = {
    NOTIFIER_PASSWORD = random_password.notifier_db.result
  }
}

resource "kubernetes_config_map" "notifier_bootstrap" {
  metadata {
    name      = "caelus-notifier-bootstrap"
    namespace = var.namespace
  }

  data = {
    "notifier-bootstrap.sql" = file("${path.module}/notifier-bootstrap.sql")
  }
}

resource "kubernetes_secret" "notifier" {
  metadata {
    name      = "caelus-notifier"
    namespace = var.namespace
  }

  type = "Opaque"

  data = {
    NOTIFIER_DATABASE_URL = format(
      "postgresql://caelus_notifier:%s@caelus-postgres.%s.svc.cluster.local:5432/%s",
      random_password.notifier_db.result, var.namespace, var.db_name,
    )
  }
}

resource "kubernetes_deployment" "notifier" {
  metadata {
    name      = "caelus-notifier"
    namespace = var.namespace
    labels = {
      app = "caelus-notifier"
    }
  }

  spec {
    # A second replica would be safe (rows are claimed with SKIP LOCKED) but
    # buys nothing.
    replicas = 1

    selector {
      match_labels = {
        app = "caelus-notifier"
      }
    }

    strategy {
      type = "Recreate"
    }

    template {
      metadata {
        labels = {
          app = "caelus-notifier"
        }
        annotations = {
          "checksum/secret" = sha256(jsonencode(kubernetes_secret.notifier.data))
        }
      }

      spec {
        automount_service_account_token = false
        # Room for a delivery in progress, three SMTP timeouts at worst, to be
        # recorded rather than repeated.
        termination_grace_period_seconds = 45

        security_context {
          run_as_non_root = true
          run_as_user     = 65534
          seccomp_profile {
            type = "RuntimeDefault"
          }
        }

        container {
          name    = "notifier"
          image   = var.notifier_image
          command = ["/notifier"]

          # The relay is a tf/deps singleton that accepts unauthenticated mail
          # from in-cluster namespaces, so there is no credential to carry.
          env {
            name  = "NOTIFIER_SMTP_HOST"
            value = "smtp.${var.mailer_namespace}.svc.cluster.local"
          }

          env {
            name  = "NOTIFIER_SMTP_PORT"
            value = "25"
          }

          env {
            name  = "NOTIFIER_SMTP_FROM"
            value = "no-reply@freepod.eu"
          }

          env_from {
            secret_ref {
              name = kubernetes_secret.notifier.metadata[0].name
            }
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
              cpu    = "5m"
              memory = "10Mi"
            }
            limits = {
              memory = "64Mi"
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
