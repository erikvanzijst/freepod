variable "api_image" {
  description = "API container image incl. registry and tag (null = workspace default: :master prod, :latest dev)"
  type        = string
  default     = null
  nullable    = true
}

variable "ui_image" {
  description = "UI container image incl. registry and tag (null = workspace default: :master prod, :latest dev)"
  type        = string
  default     = null
  nullable    = true
}

variable "builder_image" {
  description = "Image that runs tenant builds, published by ./scripts/build-images.sh --builder on its own cadence"
  type        = string
  default     = "ghcr.io/erikvanzijst/freepod/builder:0.1.6"
}

variable "environment" {
  description = "Namespace label for environment (null = workspace default)"
  type        = string
  default     = null
  nullable    = true
}

variable "reserved_hostnames" {
  description = "Hostnames that name platform infrastructure and so cannot be claimed as deployment hostnames, per Terraform workspace."
  type        = map(list(string))

  # kube.freepod.eu (the CNAME target every platform wildcard points at) and
  # blob.freepod.eu (Garage) are one instance serving both environments, so
  # they are reserved in both -- see s3_endpoint_url below.
  default = {
    default = [
      "dev.freepod.eu",
      "www.dev.freepod.eu",
      "login.dev.freepod.eu",
      "smtp.dev.freepod.eu",
      "imap.dev.freepod.eu",
      "ssh.dev.freepod.eu",
      "grafana.dev.freepod.eu",
      "prometheus.dev.freepod.eu",
      "loki.dev.freepod.eu",
      "alerts.dev.freepod.eu",
      "alertmanager.dev.freepod.eu",
      "kube.freepod.eu",
      "blob.freepod.eu",
    ]
    prod = [
      "freepod.eu",
      "www.freepod.eu",
      "keycloak.freepod.eu",
      "account.freepod.eu",
      "auth.freepod.eu",
      "login.freepod.eu",
      "smtp.freepod.eu",
      "imap.freepod.eu",
      "grafana.freepod.eu",
      "prometheus.freepod.eu",
      "loki.freepod.eu",
      "alerts.freepod.eu",
      "alertmanager.freepod.eu",
      "kube.freepod.eu",
      "blob.freepod.eu",
    ]
  }

  validation {
    condition     = alltrue([for k in ["default", "prod"] : contains(keys(var.reserved_hostnames), k)])
    error_message = "reserved_hostnames must have both a \"default\" (dev) and a \"prod\" key. The dev workspace is named `default`, not `dev`."
  }
}

# Keycloak client identity, keyed by Terraform workspace.
#
# These are maps rather than scalars because Terraform auto-loads
# `*.auto.tfvars` for EVERY workspace, so a single scalar cannot hold two
# per-environment values. Each environment now has its own Keycloak client
# (`freepod-prod` / `freepod-dev`, declared in tf/deps/keycloak-config), so a
# session minted for dev is not interchangeable with one minted for prod.
#
# The keys must be workspace names. **The dev workspace is named `default`, not
# `dev`** — see `local.is_prod_workspace`. A `dev` key would silently never
# match, so the validations below reject that mistake up front rather than
# failing later with an obscure index error.

variable "oauth2_proxy_client_ids" {
  description = "Keycloak client ID per Terraform workspace, e.g. { default = \"freepod-dev\", prod = \"freepod-prod\" }. Read from tf/deps outputs."
  type        = map(string)

  validation {
    condition     = alltrue([for k in ["default", "prod"] : contains(keys(var.oauth2_proxy_client_ids), k)])
    error_message = "oauth2_proxy_client_ids must have both a \"default\" (dev) and a \"prod\" key. The dev workspace is named `default`, not `dev`."
  }
}

variable "oauth2_proxy_client_secrets" {
  description = "Keycloak client secret per Terraform workspace. Read with `terraform output -raw freepod_{dev,prod}_client_secret` in tf/deps."
  type        = map(string)
  sensitive   = true

  validation {
    condition     = alltrue([for k in ["default", "prod"] : contains(keys(var.oauth2_proxy_client_secrets), k)])
    error_message = "oauth2_proxy_client_secrets must have both a \"default\" (dev) and a \"prod\" key. The dev workspace is named `default`, not `dev`."
  }
}

variable "oauth2_proxy_cookie_secret" {
  description = "Cookie secret for oauth2-proxy (32 bytes, base64 encoded)"
  type        = string
  sensitive   = true
}

variable "smtp_password" {
  description = "SMTP password for outbound email (use secrets.auto.tfvars)"
  type        = string
  sensitive   = true
}

variable "smtp_username" {
  description = "SMTP username for outbound email"
  type        = string
  default     = "noreply@freepod.eu"
}

variable "db_password" {
  description = "Postgres password (use secrets.auto.tfvars)"
  type        = string
  sensitive   = true
}

variable "var_encryption_keys" {
  description = <<-EOT
    Fernet keys for deployment vars, per workspace, newest first. Set in
    secrets.auto.tfvars, e.g.

      var_encryption_keys = {
        dev  = ["<newest>", "<previous>"]
        prod = ["<newest>"]
      }

    Generate one with:

      python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  EOT
  type        = map(list(string))
  default     = {}
  sensitive   = true
}

variable "mollie_api_key" {
  description = "Mollie API Key"
  type        = string
  sensitive   = true
}

# The SSH edge's upstream keypair, keyed by Terraform workspace.
#
# Generate one with:
#
#   ssh-keygen -t ed25519 -N "" -C freepod-upstream-<env> -f /tmp/k && cat /tmp/k
#
# Rotating it is a fleet-wide operation -- every sidecar trusts the public half
# -- so plan it as a two-step chart change. See ssh-auth/README.md.
variable "sshpiper_upstream_private_keys" {
  description = "OpenSSH private key the edge authenticates to sidecars with, per Terraform workspace. Set in secrets.auto.tfvars."
  type        = map(string)
  sensitive   = true

  validation {
    condition     = alltrue([for k in ["default", "prod"] : contains(keys(var.sshpiper_upstream_private_keys), k)])
    error_message = "sshpiper_upstream_private_keys must have both a \"default\" (dev) and a \"prod\" key. The dev workspace is named `default`, not `dev`."
  }

  validation {
    condition = (
      !alltrue([for k in ["default", "prod"] : contains(keys(var.sshpiper_upstream_private_keys), k)])
      || var.sshpiper_upstream_private_keys["default"] != var.sshpiper_upstream_private_keys["prod"]
    )
    error_message = "The dev and prod upstream keys must differ: one key for both environments would let the dev edge authenticate to a prod tenant's sidecar."
  }
}

variable "sshpiper_host_private_keys" {
  description = "OpenSSH private key the edge authenticates to itself with, per Terraform workspace. Set in secrets.auto.tfvars."
  type        = map(string)
  sensitive   = true

  validation {
    condition     = alltrue([for k in ["default", "prod"] : contains(keys(var.sshpiper_host_private_keys), k)])
    error_message = "sshpiper_host_private_keys must have both a \"default\" (dev) and a \"prod\" key. The dev workspace is named `default`, not `dev`."
  }
}

# The resolver image. Immutable tag from ssh-auth/VERSION, never re-pushed, and
# deliberately not a moving tag like the API's: the SSH edge must not roll
# because the API rolled. Bump it here to deploy a new resolver.
variable "ssh_resolver_image" {
  description = "SSH auth resolver image (ssh-auth/), pinned to an immutable version"
  type        = string
  default     = "ghcr.io/erikvanzijst/freepod/ssh-resolver:0.1.3"
}

variable "sshpiper_port" {
  description = "Cluster-side SSH port for the SFTP entry point (null = workspace default: 2222 prod, 2223 dev)"
  type        = number
  default     = null
  nullable    = true
}

# Garage S3 object store, keyed by Terraform workspace.
#
# Maps for the same reason as oauth2_proxy_client_ids above: `*.auto.tfvars` is
# auto-loaded for EVERY workspace, so a scalar cannot hold two per-environment
# values. One Garage instance serves both environments (tf/deps is
# workspace-less) and they are separated by bucket and access key, so getting
# this wrong does not fail loudly — it silently points dev at prod's objects.
# Hence the validations, and the same reminder: **the dev workspace is named
# `default`, not `dev`**.
#
# Read the values from tf/deps:
#   terraform output -raw garage_access_key_id_dev
#   terraform output -raw garage_secret_access_key_dev   (and the prod pair)

variable "s3_buckets" {
  description = "Garage bucket per Terraform workspace, e.g. { default = \"dev\", prod = \"prod\" }."
  type        = map(string)
  default = {
    default = "dev"
    prod    = "prod"
  }

  validation {
    condition     = alltrue([for k in ["default", "prod"] : contains(keys(var.s3_buckets), k)])
    error_message = "s3_buckets must have both a \"default\" (dev) and a \"prod\" key. The dev workspace is named `default`, not `dev`."
  }
}

variable "s3_access_key_ids" {
  description = "Garage S3 access key ID per Terraform workspace. Read from tf/deps outputs."
  type        = map(string)

  validation {
    condition     = alltrue([for k in ["default", "prod"] : contains(keys(var.s3_access_key_ids), k)])
    error_message = "s3_access_key_ids must have both a \"default\" (dev) and a \"prod\" key. The dev workspace is named `default`, not `dev`."
  }
}

variable "s3_secret_access_keys" {
  description = "Garage S3 secret access key per Terraform workspace. Read with `terraform output -raw garage_secret_access_key_{dev,prod}` in tf/deps."
  type        = map(string)
  sensitive   = true

  validation {
    condition     = alltrue([for k in ["default", "prod"] : contains(keys(var.s3_secret_access_keys), k)])
    error_message = "s3_secret_access_keys must have both a \"default\" (dev) and a \"prod\" key. The dev workspace is named `default`, not `dev`."
  }
}

# Scalars, not maps: one Garage serves both environments at one hostname.
variable "s3_endpoint_url" {
  description = "Garage S3 endpoint. Path-style addressing is mandatory — see api/app/config.py."
  type        = string
  default     = "https://blob.freepod.eu"
}

variable "s3_region" {
  description = "SigV4 signing region. Garage's default; must match tf/deps."
  type        = string
  default     = "garage"
}

# --- Per-deployment object storage ------------------------------------------
# The API provisions a bucket and access key per storage-enabled deployment, so
# it needs a Garage admin credential of its own. Not per-workspace, unlike the S3
# credentials above: every environment provisions on the one shared instance and
# the scope is identical, so both workspaces take the same value.
#
# `terraform output -raw garage_caelus_api_admin_token` in tf/deps.

variable "garage_admin_url" {
  description = "In-cluster Garage admin API URL. Never routed by an Ingress; see tf/deps/garage/ingress.tf."
  type        = string
  default     = "http://garage.garage.svc.cluster.local:3903"
}

variable "garage_admin_token" {
  description = "Scoped, non-expiring Garage admin token for per-deployment bucket provisioning. From tf/deps."
  type        = string
  sensitive   = true
}

variable "loki_base_url" {
  description = "In-cluster Loki query API URL. Never Ingress-routed; only the API may reach it."
  type        = string
  default     = "http://loki.monitoring.svc.cluster.local:3100"
}

variable "log_keepalive_seconds" {
  description = "Interval between SSE keepalives on an open log stream. Must stay below the shortest connection timeout in the client -> homelab HAProxy -> Traefik -> API path. HAProxy's timeouts are operator-configured and not in this repo, so this is a variable rather than a constant -- measure against the live edge before changing it."
  type        = number
  default     = 15
}

variable "cloudflare_api_dns_token" {
  description = "Cloudflare API token with `Zone → DNS → Edit` on the platform zone. Set in secrets.auto.tfvars; the reconciler creates each account's wildcard record with it."
  type        = string
  sensitive   = true
  default     = ""
}

variable "cloudflare_zone_id" {
  description = "Id of the platform's DNS zone."
  type        = string
  default     = ""
}

variable "dns_record_target" {
  description = "What an account's wildcard CNAME resolves to. Mirrors the platform's own `*.<domain>` record, so moving the ingress stays one edit."
  type        = string
  default     = "kube.freepod.eu"
}
