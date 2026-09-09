resource "kubernetes_deployment" "api" {
  metadata {
    name      = "caelus-api"
    namespace = var.namespace
    labels = {
      app = "caelus-api"
    }
  }

  spec {
    replicas = 1

    selector {
      match_labels = {
        app = "caelus-api"
      }
    }

    strategy {
      type = "RollingUpdate"
      rolling_update {
        max_surge       = 1
        max_unavailable = 0
      }
    }

    template {
      metadata {
        labels = {
          app = "caelus-api"
        }
        annotations = {
          "checksum/config" = sha256(jsonencode(kubernetes_config_map.api.data))
        }
      }

      spec {
        service_account_name = kubernetes_service_account.api.metadata[0].name

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

          volume_mount {
            name       = "sqlite-data"
            mount_path = "/app/db"
          }
        }

        # Applies the catalog baked into the image at /app/products/catalog.
        # Init containers run in order, so this always follows `migrate` and can
        # rely on the schema being current. A malformed catalog exits non-zero,
        # which fails the init container: the new pod never becomes ready and
        # the previous ReplicaSet keeps serving the prior catalog.
        init_container {
          name              = "catalog"
          image             = var.api_image
          image_pull_policy = "Always"
          command           = ["caelus", "catalog", "apply"]

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

          # The reconciler materializes product icons into CAELUS_STATIC_PATH,
          # so it needs the same persistent volume the API serves them from.
          # Without this mount the icons would be written to the init
          # container's ephemeral filesystem and vanish, leaving every curated
          # product with a stored rel_icon_path pointing at a missing file.
          volume_mount {
            name       = "static-data"
            mount_path = "/var/static"
          }
        }

        container {
          image             = var.api_image
          image_pull_policy = "Always"
          name              = "api"

          port {
            name           = "http"
            container_port = 8000
            protocol       = "TCP"
          }

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

          # Garage S3 endpoint, bucket and access key for this environment.
          # Only the API gets these: it is the sole holder of the credentials
          # and the only thing that mints presigned URLs. Deliberately NOT on
          # the worker (worker.tf) — nothing there reads objects yet, and an
          # unused credential in a second pod is only extra exposure. Add it
          # there when, and only when, a worker task actually needs it.
          env_from {
            secret_ref {
              name = kubernetes_secret.s3.metadata[0].name
            }
          }

          # The DNS credential, because `caelus reconcile` is run from this pod
          # and reconciling is what creates an account's wildcard record.
          env_from {
            secret_ref {
              name = kubernetes_secret.dns.metadata[0].name
            }
          }

          # The var keyring. The API is where vars are written, and it verifies
          # this keyring covers everything already stored before it will serve
          # a single request -- a row whose key is gone can never be decrypted
          # again, and that has to surface here rather than inside a tenant's
          # later rollout.
          env_from {
            secret_ref {
              name = kubernetes_secret.var_keys.metadata[0].name
            }
          }

          volume_mount {
            name       = "sqlite-data"
            mount_path = "/app/db"
          }

          volume_mount {
            name       = "static-data"
            mount_path = "/var/static"
          }

          # resources {
          #   requests = {
          #     memory = "128Mi"
          #     cpu    = "100m"
          #   }
          #   limits = {
          #     memory = "256Mi"
          #     cpu    = "200m"
          #   }
          # }
        }
        volume {
          name = "sqlite-data"
          persistent_volume_claim {
            claim_name = kubernetes_persistent_volume_claim.sqlite_pvc.metadata[0].name
          }
        }
        volume {
          name = "static-data"
          persistent_volume_claim {
            claim_name = kubernetes_persistent_volume_claim.static_pvc.metadata[0].name
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

  depends_on = [kubernetes_cluster_role_binding.api]
}
