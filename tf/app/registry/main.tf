# The environment's tenant image registry. Spec: tenant-image-registry,
# registry-authorization · Rationale: authenticated-tenant-registry.

locals {
  labels = {
    app = "registry"
  }

  config_dir  = "/etc/distribution/conf"
  storage_dir = "/var/lib/registry"
  tls_secret  = "registry-tls"

  config = yamlencode({
    version = "0.1"
    log = {
      level  = "info"
      fields = { service = "registry" }
    }
    storage = {
      filesystem = { rootdirectory = local.storage_dir }
      delete     = { enabled = true }
      cache      = { blobdescriptor = "inmemory" }
    }
    http = {
      addr = ":5000"
      tls = {
        certificate = "/etc/distribution/tls/tls.crt"
        key         = "/etc/distribution/tls/tls.key"
      }
      headers = {
        "X-Content-Type-Options" = ["nosniff"]
      }
    }
    auth = {
      token = {
        realm             = var.token_realm
        service           = var.host
        issuer            = var.token_issuer
        jwks              = "/etc/distribution/jwks/jwks.json"
        signingalgorithms = ["ES256"]
      }
    }
  })

  pod_security_context = {
    run_as_user  = 1000
    run_as_group = 1000
  }

  probe = [
    "sh", "-c",
    "wget -q -O /dev/null --no-check-certificate https://127.0.0.1:5000/v2/ 2>&1 | grep -q ' 401 '",
  ]
}

resource "kubernetes_config_map" "config" {
  metadata {
    name      = "registry-config"
    namespace = var.namespace
  }

  data = {
    "config.yml" = local.config
  }
}

resource "kubernetes_config_map" "jwks" {
  metadata {
    name      = "registry-jwks"
    namespace = var.namespace
  }

  data = {
    "jwks.json" = var.jwks
  }
}

resource "kubernetes_manifest" "certificate" {
  manifest = {
    apiVersion = "cert-manager.io/v1"
    kind       = "Certificate"
    metadata = {
      name      = "registry"
      namespace = var.namespace
    }
    spec = {
      secretName = local.tls_secret
      issuerRef = {
        name = var.cluster_issuer
        kind = "ClusterIssuer"
      }
      dnsNames = [var.host]
    }
  }
}

resource "kubernetes_persistent_volume_claim" "registry" {
  metadata {
    name      = "registry"
    namespace = var.namespace
  }

  spec {
    access_modes = ["ReadWriteOnce"]
    resources {
      requests = {
        storage = var.storage_size
      }
    }
  }

  # local-path binds on first consumer, which is the Deployment below.
  wait_until_bound = false
}

resource "kubernetes_deployment" "registry" {
  metadata {
    name      = "registry"
    namespace = var.namespace
    labels    = local.labels
  }

  spec {
    replicas = 1

    strategy {
      type = "Recreate"
    }

    selector {
      match_labels = local.labels
    }

    template {
      metadata {
        labels = local.labels
        annotations = {
          "checksum/config" = sha256(join("\n", [local.config, var.jwks]))
        }
      }

      spec {
        automount_service_account_token = false

        # The Service is named `registry`, so its links would inject
        # REGISTRY_* variables, which the registry reads as config overrides.
        enable_service_links = false

        security_context {
          run_as_non_root = true
          run_as_user     = local.pod_security_context.run_as_user
          run_as_group    = local.pod_security_context.run_as_group
          fs_group        = local.pod_security_context.run_as_group
          seccomp_profile {
            type = "RuntimeDefault"
          }
        }

        # Collection is stop-the-world, and Recreate means nothing serves while
        # this runs (D16). It fails on a store missing either directory, which
        # is every store before its first push.
        init_container {
          name  = "garbage-collect"
          image = var.image
          command = [
            "sh", "-c",
            "mkdir -p ${local.storage_dir}/docker/registry/v2/repositories ${local.storage_dir}/docker/registry/v2/blobs && exec registry garbage-collect --delete-untagged ${local.config_dir}/config.yml",
          ]

          security_context {
            run_as_non_root            = true
            allow_privilege_escalation = false
            read_only_root_filesystem  = true
            capabilities {
              drop = ["ALL"]
            }
          }

          volume_mount {
            name       = "config"
            mount_path = local.config_dir
            read_only  = true
          }

          volume_mount {
            name       = "storage"
            mount_path = local.storage_dir
          }
        }

        container {
          name  = "registry"
          image = var.image
          args  = ["${local.config_dir}/config.yml"]

          port {
            name           = "https"
            container_port = 5000
            protocol       = "TCP"
          }

          readiness_probe {
            exec {
              command = local.probe
            }
            period_seconds  = 15
            timeout_seconds = 5
          }

          liveness_probe {
            exec {
              command = local.probe
            }
            initial_delay_seconds = 10
            period_seconds        = 30
            timeout_seconds       = 5
          }

          resources {
            requests = {
              cpu    = "50m"
              memory = "64Mi"
            }
            limits = {
              memory = "512Mi"
            }
          }

          security_context {
            run_as_non_root            = true
            allow_privilege_escalation = false
            read_only_root_filesystem  = true
            capabilities {
              drop = ["ALL"]
            }
          }

          volume_mount {
            name       = "config"
            mount_path = local.config_dir
            read_only  = true
          }

          volume_mount {
            name       = "jwks"
            mount_path = "/etc/distribution/jwks"
            read_only  = true
          }

          volume_mount {
            name       = "tls"
            mount_path = "/etc/distribution/tls"
            read_only  = true
          }

          volume_mount {
            name       = "storage"
            mount_path = local.storage_dir
          }
        }

        volume {
          name = "config"
          config_map {
            name = kubernetes_config_map.config.metadata[0].name
          }
        }

        volume {
          name = "jwks"
          config_map {
            name = kubernetes_config_map.jwks.metadata[0].name
          }
        }

        volume {
          name = "tls"
          secret {
            secret_name = local.tls_secret
          }
        }

        volume {
          name = "storage"
          persistent_volume_claim {
            claim_name = kubernetes_persistent_volume_claim.registry.metadata[0].name
          }
        }
      }
    }
  }

  # The pod cannot start until cert-manager has issued the Secret it mounts.
  wait_for_rollout = false

  lifecycle {
    ignore_changes = [
      spec[0].template[0].metadata[0].annotations["kubectl.kubernetes.io/restartedAt"],
    ]
  }

  depends_on = [kubernetes_manifest.certificate]
}

resource "kubernetes_service" "registry" {
  metadata {
    name      = "registry"
    namespace = var.namespace
  }

  spec {
    type       = "ClusterIP"
    cluster_ip = var.cluster_ip
    selector   = local.labels

    port {
      name        = "https"
      port        = 443
      target_port = "https"
      protocol    = "TCP"
    }
  }
}

# The registry reads its certificate only at startup, so a weekly restart is
# what puts a renewed one in service (D3) -- and, through the init container
# above, what collects garbage.
resource "kubernetes_service_account" "restart" {
  metadata {
    name      = "registry-restart"
    namespace = var.namespace
  }
}

resource "kubernetes_role" "restart" {
  metadata {
    name      = "registry-restart"
    namespace = var.namespace
  }

  rule {
    api_groups     = ["apps"]
    resources      = ["deployments"]
    resource_names = [kubernetes_deployment.registry.metadata[0].name]
    verbs          = ["get", "patch"]
  }
}

resource "kubernetes_role_binding" "restart" {
  metadata {
    name      = "registry-restart"
    namespace = var.namespace
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Role"
    name      = kubernetes_role.restart.metadata[0].name
  }

  subject {
    kind      = "ServiceAccount"
    name      = kubernetes_service_account.restart.metadata[0].name
    namespace = var.namespace
  }
}

resource "kubernetes_cron_job_v1" "restart" {
  metadata {
    name      = "registry-restart"
    namespace = var.namespace
  }

  spec {
    schedule                      = var.restart_schedule
    concurrency_policy            = "Forbid"
    successful_jobs_history_limit = 1
    failed_jobs_history_limit     = 1

    job_template {
      metadata {}

      spec {
        backoff_limit = 2

        template {
          metadata {}

          spec {
            service_account_name = kubernetes_service_account.restart.metadata[0].name
            restart_policy       = "Never"

            security_context {
              run_as_non_root = true
              run_as_user     = 65532
              run_as_group    = 65532
              seccomp_profile {
                type = "RuntimeDefault"
              }
            }

            container {
              name  = "restart"
              image = var.kubectl_image
              command = [
                "kubectl", "rollout", "restart",
                "deployment/${kubernetes_deployment.registry.metadata[0].name}",
                "--namespace", var.namespace,
              ]

              security_context {
                run_as_non_root            = true
                allow_privilege_escalation = false
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
