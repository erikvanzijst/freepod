resource "kubernetes_secret" "db" {
  metadata {
    name      = "caelus-db"
    namespace = var.namespace
  }

  type = "Opaque"

  data = {
    username = var.db_user
    password = var.db_password
    database = var.db_name
  }
}

# Garage S3 credentials for this environment, consumed by the API through
# `env_from` exactly like caelus-db above.
#
# Only this environment's bucket and key are here. The key carries read+write on
# that one bucket and nothing else, so a leaked or misconfigured dev credential
# cannot reach prod objects — verified at the Garage end, not merely by
# convention.
#
# The endpoint and region are not secret, but they ride along in the same Secret
# so the API gets its whole S3 configuration from one `env_from` and there is no
# way to update the credentials while leaving a stale endpoint behind.
resource "kubernetes_secret" "s3" {
  metadata {
    name      = "caelus-s3"
    namespace = var.namespace
  }

  type = "Opaque"

  data = {
    CAELUS_S3_ENDPOINT_URL      = var.s3_endpoint_url
    CAELUS_S3_REGION            = var.s3_region
    CAELUS_S3_BUCKET            = var.s3_bucket
    CAELUS_S3_ACCESS_KEY_ID     = var.s3_access_key_id
    CAELUS_S3_SECRET_ACCESS_KEY = var.s3_secret_access_key
    CAELUS_GARAGE_ADMIN_URL     = var.garage_admin_url
    CAELUS_GARAGE_ADMIN_TOKEN   = var.garage_admin_token
  }
}

# The keyring that encrypts every deployment var, mounted into the API (which
# writes vars) and the worker (which decrypts a release's snapshot into the
# tenant's namespace before Helm runs). Deliberately NOT the build worker: no
# var reaches a build, so a key there would be exposure with no use.
#
# A Secret rather than the ConfigMap next door, because this is the one value
# that can decrypt everything a tenant marked sensitive.
#
# Comma-separated, which is what the API parses: a Fernet key is urlsafe
# base64 and never contains a comma. An empty list yields an empty variable,
# which is legal exactly while no product template declares vars -- the API
# refuses to start otherwise.
resource "kubernetes_secret" "var_keys" {
  metadata {
    name      = "caelus-var-keys"
    namespace = var.namespace
  }

  type = "Opaque"

  data = {
    CAELUS_VAR_ENCRYPTION_KEYS = join(",", var.var_encryption_keys)
  }
}

resource "kubernetes_secret" "dns" {
  metadata {
    name      = "caelus-dns"
    namespace = var.namespace
  }

  type = "Opaque"

  data = {
    CAELUS_CLOUDFLARE_DNS_API_TOKEN = var.cloudflare_api_dns_token
    CAELUS_CLOUDFLARE_DNS_ZONE_ID   = var.cloudflare_zone_id
    CAELUS_DNS_RECORD_TARGET        = var.dns_record_target
  }
}
