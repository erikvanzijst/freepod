resource "kubernetes_secret_v1" "cloud_credentials" {
  metadata {
    name      = "velero-cloud-credentials"
    namespace = var.namespace
  }

  data = {
    cloud = <<-EOT
      [default]
      aws_access_key_id=${var.s3_access_key_id}
      aws_secret_access_key=${var.s3_secret_access_key}
    EOT
  }
}

# Velero creates this with a built-in password when it is missing at startup.
resource "kubernetes_secret_v1" "repo_credentials" {
  metadata {
    name      = "velero-repo-credentials"
    namespace = var.namespace
  }

  data = {
    repository-password = var.repo_password
  }
}

resource "kubernetes_secret_v1" "sse_c_key" {
  metadata {
    name      = "velero-sse-c-key"
    namespace = var.namespace
  }

  data = {
    key = var.sse_c_key
  }
}

resource "kubernetes_config_map_v1" "node_agent" {
  metadata {
    name      = "velero-node-agent"
    namespace = var.namespace
  }

  data = {
    "config.json" = jsonencode({
      # Each prepared volume holds its own pod and a mapped snapshot clone.
      loadConcurrency = { globalConfig = 1, prepareQueueLength = 1 }
      # Velero requires every field; "0" leaves it unset.
      podResources = {
        cpuRequest              = "50m"
        cpuLimit                = "0"
        memoryRequest           = "384Mi"
        memoryLimit             = "1Gi"
        ephemeralStorageRequest = "0"
        ephemeralStorageLimit   = "0"
      }
    })
  }
}

resource "kubernetes_config_map_v1" "skip_local_path" {
  metadata {
    name      = "velero-skip-local-path"
    namespace = var.namespace
  }

  data = {
    "policy.yaml" = yamlencode({
      version = "v1"
      # Node-local volumes cannot be snapshotted; the node's own backups cover them.
      volumePolicies = [{
        conditions = { storageClass = ["local-path"] }
        action     = { type = "skip" }
      }]
    })
  }
}

resource "helm_release" "velero" {
  name      = "velero"
  namespace = var.namespace
  chart     = "https://github.com/vmware-tanzu/helm-charts/releases/download/velero-12.2.5/velero-12.2.5.tgz"

  values = [
    yamlencode({
      image = { tag = "v1.18.4" }

      initContainers = [{
        name         = "velero-plugin-for-aws"
        image        = "velero/velero-plugin-for-aws:v1.14.4"
        volumeMounts = [{ mountPath = "/target", name = "plugins" }]
      }]

      credentials = { existingSecret = kubernetes_secret_v1.cloud_credentials.metadata[0].name }

      snapshotsEnabled = false
      configuration = {
        features                     = "EnableCSI"
        defaultSnapshotMoveData      = true
        defaultRepoMaintainFrequency = "24h"
        backupStorageLocation = [{
          name     = "default"
          provider = "aws"
          bucket   = var.bucket
          default  = true
          config = {
            region           = "garage"
            s3ForcePathStyle = "true"
            s3Url            = var.s3_url
            # Kopia encrypts volume data itself; this covers the backup metadata.
            customerKeyEncryptionSecret = "${kubernetes_secret_v1.sse_c_key.metadata[0].name}/key"
          }
        }]
      }

      resources = {
        requests = { cpu = "50m", memory = "128Mi" }
      }

      # Platform state is rebuilt by Terraform and the reconciler. Only claims
      # and the Secrets charts generate in-cluster cannot be.
      schedules = {
        nightly = {
          schedule = "30 0 * * *"
          template = {
            ttl                = "336h"
            snapshotMoveData   = true
            resourcePolicy     = { kind = "configmap", name = kubernetes_config_map_v1.skip_local_path.metadata[0].name }
            excludedNamespaces = ["kube-system", var.namespace]
            includedResources  = ["persistentvolumeclaims", "persistentvolumes", "secrets"]
            labelSelector = {
              matchExpressions = [{ key = "owner", operator = "NotIn", values = ["helm"] }]
            }
          }
        }
      }

      deployNodeAgent = true
      nodeAgent = {
        extraArgs   = ["--node-agent-configmap=${kubernetes_config_map_v1.node_agent.metadata[0].name}"]
        tolerations = [{ operator = "Exists" }]
        resources = {
          requests = { cpu = "20m", memory = "64Mi" }
        }
      }
    })
  ]

  depends_on = [kubernetes_secret_v1.repo_credentials, kubernetes_secret_v1.sse_c_key]
}

resource "kubernetes_config_map_v1" "cleanup" {
  metadata {
    name      = "velero-cleanup"
    namespace = var.namespace
  }

  data = {
    "cleanup.sh" = file("${path.module}/cleanup.sh")
  }
}

resource "kubernetes_service_account_v1" "cleanup" {
  metadata {
    name      = "velero-cleanup"
    namespace = var.namespace
  }
}

resource "kubernetes_role_v1" "cleanup" {
  metadata {
    name      = "velero-cleanup"
    namespace = var.namespace
  }

  rule {
    api_groups = ["velero.io"]
    resources  = ["datauploads"]
    verbs      = ["list"]
  }

  rule {
    api_groups = ["velero.io"]
    resources  = ["backuprepositories"]
    verbs      = ["list", "delete"]
  }

  rule {
    api_groups = ["batch"]
    resources  = ["jobs"]
    verbs      = ["list", "delete"]
  }
}

resource "kubernetes_role_binding_v1" "cleanup" {
  metadata {
    name      = "velero-cleanup"
    namespace = var.namespace
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Role"
    name      = kubernetes_role_v1.cleanup.metadata[0].name
  }

  subject {
    kind      = "ServiceAccount"
    name      = kubernetes_service_account_v1.cleanup.metadata[0].name
    namespace = var.namespace
  }
}

resource "kubernetes_cluster_role_v1" "cleanup" {
  metadata {
    name = "velero-cleanup"
  }

  rule {
    api_groups = [""]
    resources  = ["namespaces"]
    verbs      = ["get"]
  }
}

resource "kubernetes_cluster_role_binding_v1" "cleanup" {
  metadata {
    name = "velero-cleanup"
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "ClusterRole"
    name      = kubernetes_cluster_role_v1.cleanup.metadata[0].name
  }

  subject {
    kind      = "ServiceAccount"
    name      = kubernetes_service_account_v1.cleanup.metadata[0].name
    namespace = var.namespace
  }
}

resource "kubernetes_cron_job_v1" "cleanup" {
  metadata {
    name      = "velero-cleanup"
    namespace = var.namespace
  }

  spec {
    schedule                      = "0 6 * * *"
    concurrency_policy            = "Forbid"
    successful_jobs_history_limit = 1
    failed_jobs_history_limit     = 2

    job_template {
      metadata {}

      spec {
        backoff_limit           = 0
        active_deadline_seconds = 1800

        template {
          metadata {
            labels = {
              app = "velero-cleanup"
            }
          }

          spec {
            restart_policy       = "Never"
            service_account_name = kubernetes_service_account_v1.cleanup.metadata[0].name

            security_context {
              run_as_non_root = true
              run_as_user     = 65534
              run_as_group    = 65534
              fs_group        = 65534
            }

            container {
              name    = "cleanup"
              image   = "alpine/k8s:1.34.13"
              command = ["bash", "/script/cleanup.sh"]

              env {
                name  = "HOME"
                value = "/tmp"
              }
              env {
                name  = "VELERO_NAMESPACE"
                value = var.namespace
              }
              env {
                name  = "BUCKET"
                value = var.bucket
              }
              env {
                name  = "S3_URL"
                value = var.s3_url
              }
              env {
                name  = "AWS_DEFAULT_REGION"
                value = "garage"
              }
              env {
                name  = "AWS_SHARED_CREDENTIALS_FILE"
                value = "/credentials/cloud"
              }

              resources {
                requests = { cpu = "10m", memory = "64Mi" }
                limits   = { memory = "256Mi" }
              }

              security_context {
                allow_privilege_escalation = false
                capabilities {
                  drop = ["ALL"]
                }
              }

              volume_mount {
                name       = "script"
                mount_path = "/script"
                read_only  = true
              }
              volume_mount {
                name       = "credentials"
                mount_path = "/credentials"
                read_only  = true
              }
            }

            volume {
              name = "script"
              config_map {
                name = kubernetes_config_map_v1.cleanup.metadata[0].name
              }
            }
            volume {
              name = "credentials"
              secret {
                secret_name  = kubernetes_secret_v1.cloud_credentials.metadata[0].name
                default_mode = "0440"
              }
            }
          }
        }
      }
    }
  }
}
