# Heartbeats to healthchecks.io: each check probes its public URL from inside
# the cluster (through the public edge) and pings the outcome, so a check goes
# down both when the site fails and when the cluster stops pinging at all.

locals {
  # A probe failure pings `<url>/<curl exit code>`, which healthchecks.io
  # records as a failure, with curl's error as the event body.
  script = <<-EOT
    out=$(curl -fsS -o /dev/null -m 10 --retry 2 --retry-all-errors "$PROBE_URL" 2>&1)
    rc=$?
    echo "$PROBE_URL: exit $rc $out"
    curl -fsS -o /dev/null -m 10 --retry 3 --data-raw "$out" "$PING_URL/$rc"
  EOT
}

resource "kubernetes_secret" "ping_urls" {
  metadata {
    name      = "uptime-ping-urls"
    namespace = var.namespace
  }

  data = var.ping_urls

  lifecycle {
    precondition {
      condition     = length(setsubtract(keys(var.probes), keys(nonsensitive(var.ping_urls)))) == 0
      error_message = "Every probe needs a ping URL."
    }
  }
}

resource "kubernetes_cron_job_v1" "probe" {
  for_each = var.probes

  metadata {
    name      = "uptime-${each.key}"
    namespace = var.namespace
  }

  spec {
    schedule                      = var.schedule
    concurrency_policy            = "Forbid"
    successful_jobs_history_limit = 1
    failed_jobs_history_limit     = 1

    job_template {
      metadata {}

      spec {
        # The next minute's run is the retry; a missed ping is what alerts.
        backoff_limit           = 0
        active_deadline_seconds = 55

        template {
          metadata {
            labels = {
              app   = "uptime"
              check = each.key
            }
          }

          spec {
            restart_policy                  = "Never"
            automount_service_account_token = false
            enable_service_links            = false

            security_context {
              run_as_non_root = true
              run_as_user     = 100
              run_as_group    = 101
              seccomp_profile {
                type = "RuntimeDefault"
              }
            }

            container {
              name    = "probe"
              image   = var.image
              command = ["sh", "-c", local.script]

              env {
                name  = "PROBE_URL"
                value = each.value
              }

              env {
                name = "PING_URL"
                value_from {
                  secret_key_ref {
                    name = kubernetes_secret.ping_urls.metadata[0].name
                    key  = each.key
                  }
                }
              }

              resources {
                requests = {
                  cpu    = "10m"
                  memory = "16Mi"
                }
                limits = {
                  memory = "32Mi"
                }
              }

              security_context {
                allow_privilege_escalation = false
                read_only_root_filesystem  = true
                capabilities {
                  drop = ["ALL"]
                }
              }
            }
          }
        }
      }
    }
  }
}
