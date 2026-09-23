resource "kubernetes_deployment" "usage_worker" {
  metadata {
    name      = "caelus-usage-worker"
    namespace = var.namespace
    labels = {
      app = "caelus-usage-worker"
    }
  }

  spec {
    # A second replica would buy nothing: every write is an upsert on the
    # sample's natural key, so two samplers over one window serialize on the
    # row lock rather than sharing the work.
    replicas = 1

    selector {
      match_labels = {
        app = "caelus-usage-worker"
      }
    }

    strategy {
      type = "Recreate"
    }

    template {
      metadata {
        labels = {
          app = "caelus-usage-worker"
        }
        annotations = {
          "checksum/config" = sha256(jsonencode(kubernetes_config_map.api.data))
        }
      }

      spec {
        # Migrations run here as well as on the API, for the same reason
        # `caelus-worker` does: `api_image` is a moving tag, so a pod can start
        # on an image newer than the schema any other pod migrated to. Reaching
        # head itself is what makes this worker independent of rollout order.
        init_container {
          name              = "migrate"
          image             = var.api_image
          image_pull_policy = "Always"
          command           = ["alembic", "upgrade", "head"]

          env_from {
            config_map_ref {
              name = "caelus-api-config"
            }
          }

          env_from {
            secret_ref {
              name = "caelus-db"
            }
          }
        }

        container {
          image             = var.api_image
          image_pull_policy = "Always"
          name              = "usage-worker"
          command           = ["caelus", "usage-worker"]

          env_from {
            config_map_ref {
              name = "caelus-api-config"
            }
          }

          env_from {
            secret_ref {
              name = "caelus-db"
            }
          }

          # Deliberately no caelus-var-keys, as on db-worker: the sampler reads
          # OpenCost and writes the ledger, and decrypts no tenant secret.

          resources {
            requests = {
              memory = "128Mi"
              cpu    = "10m"
            }
            limits = {
              memory = "256Mi"
              cpu    = "200m"
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
