# Untags tenant images retention no longer keeps (tenant-image-retention
# spec). An hour ahead of the registry's restart, whose init container then
# collects what the removed tags reached, so one night untags and reclaims.
resource "kubernetes_cron_job_v1" "registry_prune" {
  metadata {
    name      = "caelus-registry-prune"
    namespace = var.namespace
  }

  spec {
    schedule                      = "0 3 * * *"
    concurrency_policy            = "Forbid"
    successful_jobs_history_limit = 1
    failed_jobs_history_limit     = 2

    job_template {
      metadata {}

      spec {
        # A failed run is retried by the next night's; removals are idempotent.
        backoff_limit           = 0
        active_deadline_seconds = 1800

        template {
          metadata {
            labels = {
              app = "caelus-registry-prune"
            }
          }

          spec {
            restart_policy = "Never"
            # Talks only to the database and the registry, never the cluster API.
            automount_service_account_token = false

            container {
              image             = var.api_image
              image_pull_policy = "Always"
              name              = "registry-prune"
              command           = ["caelus", "registry-prune"]

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

              # Mints the prune's delete capability in process.
              env_from {
                secret_ref {
                  name = kubernetes_secret.registry_signing.metadata[0].name
                }
              }
            }
          }
        }
      }
    }
  }
}
