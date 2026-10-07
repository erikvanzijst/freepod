# Read the generated credentials back out of the cluster.
#
# Terraform cannot pre-generate these: Garage mints the key material itself and
# `ImportKey` rejects keys it did not generate. So the Job creates them, writes
# them to a Secret, and this data source reads them back — the same shape as the
# Keycloak client secrets, which also only exist after an apply.
data "kubernetes_secret" "garage_keys" {
  metadata {
    name      = local.keys_secret_name
    namespace = var.namespace
  }

  # The Secret does not exist until the Job has run. `wait_for_completion` on
  # the Job means this is read after provisioning succeeded, not during.
  depends_on = [kubernetes_job.provision]
}

# `nonsensitive()` because an access key ID is an identifier, not a credential.
# The whole `data` map of a kubernetes_secret data source is sensitive-marked,
# and that marking propagates to anything derived from it — so without this,
# every consumer would have to declare the key ID sensitive too, and
# `terraform output` / `terraform plan` would show `(sensitive value)` where the
# operator most needs to read it. The ID is not secret by any measure — it travels in the clear in the
# `X-Amz-Credential` parameter of every presigned URL this store hands out.
#
# The secret access key below keeps its marking, which is the half that matters.
output "access_key_id" {
  description = "The platform's S3 access key ID. Not a credential on its own."
  value       = nonsensitive(data.kubernetes_secret.garage_keys.data["access_key_id"])
}

output "secret_access_key" {
  description = "The platform's S3 secret access key."
  value       = data.kubernetes_secret.garage_keys.data["secret_access_key"]
  sensitive   = true
}

# Single-sourced from the same local the provisioning Job is given, so the API
# cannot drift from what was actually created.
output "bucket" {
  description = "The platform's own S3 bucket."
  value       = local.bucket_name
}

# The Caelus API's admin credential for per-deployment bucket provisioning.
# Sensitive with no `nonsensitive()` escape hatch: unlike an access key ID, every
# byte of this is the credential. It is scoped (no cluster status, no layout, no
# minting further tokens) but within that scope it can read back the secret of
# any access key, so it is the one output here that must never be printed
# casually.
output "caelus_api_admin_token" {
  description = "Scoped, non-expiring Garage admin token for the Caelus API's per-deployment provisioning."
  value       = data.kubernetes_secret.garage_keys.data[local.api_token_secret_key]
  sensitive   = true
}

# The admin API, for the Caelus API's per-deployment provisioning. In-cluster
# only and deliberately so: ingress.tf routes :3900 and nothing routes :3903.
# This is the headless governing Service rather than `garage-s3`, because that
# one exposes the S3 port alone precisely so no Ingress can reach admin by
# mistake — see garage.tf.
output "admin_url" {
  description = "In-cluster Garage admin API URL. Not reachable from outside the cluster."
  value       = "http://${kubernetes_service.garage.metadata[0].name}.${var.namespace}.svc.cluster.local:3903"
}

output "s3_endpoint" {
  description = "Public S3 endpoint URL, for the Caelus API's S3 client."
  value       = "https://${var.host}"
}

output "s3_region" {
  description = "SigV4 signing region. Must match on both sides."
  value       = local.s3_region
}
