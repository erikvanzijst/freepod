resource "kubernetes_deployment" "build_worker" {
  metadata {
    name      = "caelus-build-worker"
    namespace = var.namespace
    labels = {
      app = "caelus-build-worker"
    }
  }

  spec {
    # Concurrency is `CAELUS_BUILD_MAX_IN_FLIGHT`, not this number. One worker
    # advances every running build on each pass without blocking on any of
    # them, so more replicas would buy nothing but contention.
    replicas = 1

    selector {
      match_labels = {
        app = "caelus-build-worker"
      }
    }

    # Recreate, unlike the reconcile worker's RollingUpdate. A rolling update
    # briefly runs two workers, and two workers can each observe "nothing
    # running" and each claim a build, momentarily exceeding the in-flight
    # limit on a node that has no headroom for it. The cost is a few seconds
    # with no worker, which is invisible: builds are advanced by the next pass.
    strategy {
      type = "Recreate"
    }

    template {
      metadata {
        labels = {
          app = "caelus-build-worker"
        }

        # Roll the pod when the config changes.
        annotations = {
          "checksum/config" = sha256(jsonencode(kubernetes_config_map.api.data))
        }
      }

      spec {
        # The API's ServiceAccount, which already holds the cluster permissions
        # needed to create, read and delete Jobs and to read pod logs in the
        # builds namespace. Reused rather than given its own so there is one
        # platform identity to reason about.
        service_account_name = kubernetes_service_account.api.metadata[0].name

        container {
          image             = var.api_image
          image_pull_policy = "Always"
          name              = "build-worker"
          command           = ["caelus", "build-worker"]

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

          env_from {
            secret_ref {
              name = kubernetes_secret.s3.metadata[0].name
            }
          }

          # Mints each build's capability in process; the key itself never
          # reaches a build pod.
          env_from {
            secret_ref {
              name = kubernetes_secret.registry_signing.metadata[0].name
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

  depends_on = [kubernetes_cluster_role_binding.api]
}
