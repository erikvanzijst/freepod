# Bucket, access-key and lifecycle provisioning (design D2).
#
# Garage has no IAM, so there is no S3-policy-shaped Terraform resource to use,
# and `ImportKey` rejects keys Garage did not generate — so the tidy pattern of
# "Terraform generates the credential, tells Garage, writes the Secret from
# state" is unavailable. Garage must mint the key and something must read it
# back. That something is this Job.
#
# Re-running it on every apply is deliberate: it makes provisioning declarative
# in effect even though Garage offers no declarative surface, and it repairs
# hand-made drift. Every step in the script reads before it writes, so a re-run
# never rotates an existing key.

locals {
  keys_secret_name = "garage-keys"

  # The Caelus API's own admin token: a *second* credential in the same Secret,
  # scoped to the per-deployment bucket and key operations the API performs at
  # reconcile time. Unlike an access key, an admin token's secret cannot be read
  # back from Garage — CreateAdminToken shows it once — so this Secret is its
  # only store of record, and the script reads it from here on re-runs.
  api_token_name       = "caelus-api-provisioning"
  api_token_secret_key = "caelus_api_admin_token"

  provision_script = file("${path.module}/scripts/provision.sh")

  # Job specs are immutable, so the Job is named after a digest of everything
  # that determines what it does. Change the script, the environment list or the
  # expiry, and Terraform replaces the Job — which is what "re-run when the
  # script ConfigMap changes" means in practice.
  provision_hash = substr(sha256(join("\n", [
    local.provision_script,
    local.bucket_name,
    local.key_name,
    tostring(var.object_expiry_days),
    var.kubectl_image,
    local.api_token_name,
    local.api_token_secret_key,
  ])), 0, 10)

  # The platform's own bucket and S3 key on this instance, e.g. for build
  # artifacts. Tenant buckets are `dep-<id>`, so this cannot collide.
  bucket_name = "artifacts"
  key_name    = "caelus-api"
}

resource "kubernetes_service_account" "provisioner" {
  metadata {
    name      = "garage-provisioner"
    namespace = var.namespace
  }
}

# Scoped to writing one Secret in this one namespace. No cross-namespace
# permission: the Job must not write into tf/app's namespaces, which would
# invert the ownership boundary between the two root modules (design D2).
resource "kubernetes_role" "provisioner" {
  metadata {
    name      = "garage-provisioner"
    namespace = var.namespace
  }

  # `create` cannot be constrained by resourceNames — at authorization time the
  # object does not exist yet, so Kubernetes ignores resourceNames on create and
  # a rule carrying them would simply never authorize it. Hence two rules: an
  # unnamed create, and everything else pinned to the one Secret.
  rule {
    api_groups = [""]
    resources  = ["secrets"]
    verbs      = ["create"]
  }

  rule {
    api_groups     = [""]
    resources      = ["secrets"]
    resource_names = [local.keys_secret_name]
    # `kubectl apply` reads, then PATCHes; `update` covers the non-apply path.
    verbs = ["get", "update", "patch"]
  }
}

resource "kubernetes_role_binding" "provisioner" {
  metadata {
    name      = "garage-provisioner"
    namespace = var.namespace
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Role"
    name      = kubernetes_role.provisioner.metadata[0].name
  }

  subject {
    kind      = "ServiceAccount"
    name      = kubernetes_service_account.provisioner.metadata[0].name
    namespace = var.namespace
  }
}

resource "kubernetes_config_map" "provisioner_scripts" {
  metadata {
    name      = "garage-provisioner-scripts"
    namespace = var.namespace
  }

  data = {
    "provision.sh" = local.provision_script
  }
}

resource "kubernetes_job" "provision" {
  metadata {
    name      = "garage-provision-${local.provision_hash}"
    namespace = var.namespace
  }

  spec {
    backoff_limit = 3

    template {
      metadata {
        labels = { app = "garage-provisioner" }
      }

      spec {
        service_account_name = kubernetes_service_account.provisioner.metadata[0].name
        restart_policy       = "Never"

        # Buckets, access keys, permission grants and bucket lifecycle rules —
        # all of it over the Garage admin API, in one container. See the header
        # of scripts/provision.sh for why this cannot run in the Garage image
        # (FROM scratch, no shell) and why the CLI is not usable from a second
        # pod (RPC needs the node ID).
        container {
          name    = "provision"
          image   = var.kubectl_image
          command = ["/bin/sh", "/scripts/provision.sh"]

          env {
            name = "GARAGE_ADMIN_URL"
            # The headless Service, which publishes not-ready addresses: on a
            # fresh install Garage is deliberately unready until its layout is
            # committed, and this step exists precisely to say so.
            value = "http://${kubernetes_service.garage.metadata[0].name}.${var.namespace}.svc.cluster.local:3903"
          }

          env {
            name = "GARAGE_ADMIN_TOKEN"
            value_from {
              secret_key_ref {
                name = kubernetes_secret.garage.metadata[0].name
                key  = "admin_token"
              }
            }
          }

          env {
            name  = "BUCKET_NAME"
            value = local.bucket_name
          }

          env {
            name  = "KEY_NAME"
            value = local.key_name
          }

          env {
            name  = "KEYS_SECRET_NAME"
            value = local.keys_secret_name
          }

          env {
            name  = "NAMESPACE"
            value = var.namespace
          }

          env {
            name  = "OBJECT_EXPIRY_DAYS"
            value = tostring(var.object_expiry_days)
          }

          env {
            name  = "API_TOKEN_NAME"
            value = local.api_token_name
          }

          env {
            name  = "API_TOKEN_SECRET_KEY"
            value = local.api_token_secret_key
          }

          # Long enough that an operator can complete the one-time layout
          # bootstrap in another terminal while the apply waits, short enough
          # that an unattended apply fails with a useful message rather than
          # hanging indefinitely.
          env {
            name  = "HEALTH_TIMEOUT_SECONDS"
            value = "600"
          }

          volume_mount {
            name       = "scripts"
            mount_path = "/scripts"
            read_only  = true
          }
        }

        volume {
          name = "scripts"
          config_map {
            name         = kubernetes_config_map.provisioner_scripts.metadata[0].name
            default_mode = "0555"
          }
        }
      }
    }
  }

  # Terraform blocks the apply until provisioning has actually succeeded, so
  # the data source below reads a Secret that exists. The generous timeout is
  # the health wait at the top of the script (see HEALTH_TIMEOUT_SECONDS).
  wait_for_completion = true

  timeouts {
    create = "20m"
    update = "20m"
  }

  depends_on = [
    kubernetes_stateful_set.garage,
    kubernetes_role_binding.provisioner,
  ]
}
