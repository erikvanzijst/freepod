resource "kubernetes_deployment" "postgres" {
  metadata {
    name      = "caelus-postgres"
    namespace = var.namespace
    labels = {
      app = "caelus-postgres"
    }
  }

  spec {
    replicas = 1

    selector {
      match_labels = {
        app = "caelus-postgres"
      }
    }

    strategy {
      type = "Recreate"
    }

    template {
      metadata {
        labels = {
          app = "caelus-postgres"
        }
      }

      spec {
        container {
          image = "postgres:16-alpine"
          name  = "postgres"

          env {
            name  = "POSTGRES_DB"
            value = var.db_name
          }

          env {
            name  = "POSTGRES_USER"
            value = var.db_user
          }

          env {
            name = "POSTGRES_PASSWORD"
            value_from {
              secret_key_ref {
                name = "caelus-db"
                key  = "password"
              }
            }
          }

          port {
            name           = "postgres"
            container_port = 5432
            protocol       = "TCP"
          }

          volume_mount {
            name       = "postgres-data"
            mount_path = "/var/lib/postgresql/data"
          }

          resources {
            requests = {
              memory = "128Mi"
              cpu    = "100m"
            }
            limits = {
              memory = "256Mi"
              cpu    = "200m"
            }
          }

          liveness_probe {
            exec {
              command = ["pg_isready", "-U", var.db_user]
            }
            initial_delay_seconds = 30
            period_seconds        = 10
            timeout_seconds       = 5
            failure_threshold     = 3
          }

          readiness_probe {
            exec {
              command = ["pg_isready", "-U", var.db_user]
            }
            initial_delay_seconds = 5
            period_seconds        = 5
            timeout_seconds       = 3
            failure_threshold     = 3
          }
        }

        volume {
          name = "postgres-data"
          persistent_volume_claim {
            claim_name = kubernetes_persistent_volume_claim.postgres_pvc.metadata[0].name
          }
        }
      }
    }
  }

  depends_on = [kubernetes_secret.db]

  lifecycle {
    ignore_changes = [
      spec[0].template[0].metadata[0].annotations["kubectl.kubernetes.io/restartedAt"],
    ]
  }
}

resource "kubernetes_service" "postgres" {
  metadata {
    name      = "caelus-postgres"
    namespace = var.namespace
  }

  spec {
    selector = {
      app = "caelus-postgres"
    }

    port {
      name        = "postgres"
      port        = 5432
      target_port = "postgres"
    }

    cluster_ip = "None"
  }
}
