# The bucket size exporter (daemons/bucket-exporter): every deployment bucket's
# size, read one bucket per call at a fixed rate and published for Prometheus,
# where the usage sampler reads it. Beside Garage, in its namespace, with a
# token that can only list buckets and read their info (scripts/provision.sh).
#
# Spec: openspec/specs/bucket-size-exporter/spec.md

resource "kubernetes_deployment" "bucket_exporter" {
  metadata {
    name      = "bucket-exporter"
    namespace = var.namespace
    labels    = { app = "bucket-exporter" }
  }

  # The token is in the Secret only once provisioning has run.
  depends_on = [kubernetes_job.provision]

  spec {
    replicas = 1

    # One exporter at a time: the load on Garage is the rate, not twice it.
    strategy {
      type = "Recreate"
    }

    selector {
      match_labels = { app = "bucket-exporter" }
    }

    template {
      metadata {
        labels = { app = "bucket-exporter" }
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
          name    = "bucket-exporter"
          image   = var.bucket_exporter_image
          command = ["/bucket-exporter"]

          port {
            name           = "metrics"
            container_port = 9100
          }

          env {
            name  = "GARAGE_ADMIN_URL"
            value = "http://${kubernetes_service.garage.metadata[0].name}.${var.namespace}.svc.cluster.local:3903"
          }

          env {
            name = "GARAGE_ADMIN_TOKEN"
            value_from {
              secret_key_ref {
                name = local.keys_secret_name
                key  = local.exporter_token_secret_key
              }
            }
          }

          env {
            name  = "GARAGE_NAMESPACE"
            value = var.namespace
          }

          env {
            name  = "LOKI_URL"
            value = var.loki_base_url
          }

          env {
            name  = "PROMETHEUS_URL"
            value = var.prometheus_base_url
          }

          env {
            name  = "READ_RATE"
            value = tostring(var.bucket_exporter_read_rate)
          }

          readiness_probe {
            http_get {
              path = "/healthz"
              port = "metrics"
            }
            period_seconds = 10
          }

          security_context {
            allow_privilege_escalation = false
            read_only_root_filesystem  = true
            capabilities {
              drop = ["ALL"]
            }
          }

          # Idle is the steady state: a few reads a second at most.
          resources {
            requests = {
              cpu    = "5m"
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

# Scraped through the annotation, like the tenant database exporter. ClusterIP
# and never routed: sizes are for the cluster only.
resource "kubernetes_service" "bucket_exporter" {
  metadata {
    name      = "bucket-exporter"
    namespace = var.namespace
    annotations = {
      "prometheus.io/scrape" = "true"
      "prometheus.io/port"   = "9100"
    }
  }

  spec {
    selector = { app = "bucket-exporter" }

    port {
      name        = "metrics"
      port        = 9100
      target_port = "metrics"
    }
  }
}
