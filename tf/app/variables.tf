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
  default     = "ghcr.io/erikvanzijst/freepod/builder:0.4.0"
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
  # blob.freepod.eu (prod's object store) are reserved in both.
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
      "cr.dev.freepod.eu",
      "kube.freepod.eu",
      "blob.freepod.eu",
      "blob.dev.freepod.eu",
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
      "cr.freepod.eu",
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

variable "app_auth_client_ids" {
  description = "Keycloak client ID of the app-authentication broker per Terraform workspace, e.g. { default = \"freepod-apps-dev\", prod = \"freepod-apps-prod\" }. Read from tf/deps outputs."
  type        = map(string)

  validation {
    condition     = alltrue([for k in ["default", "prod"] : contains(keys(var.app_auth_client_ids), k)])
    error_message = "app_auth_client_ids must have both a \"default\" (dev) and a \"prod\" key. The dev workspace is named `default`, not `dev`."
  }
}

variable "app_auth_client_secrets" {
  description = "Keycloak client secret of the app-authentication broker per Terraform workspace. Read with `terraform output -raw freepod_apps_{dev,prod}_client_secret` in tf/deps."
  type        = map(string)
  sensitive   = true

  validation {
    condition     = alltrue([for k in ["default", "prod"] : contains(keys(var.app_auth_client_secrets), k)])
    error_message = "app_auth_client_secrets must have both a \"default\" (dev) and a \"prod\" key. The dev workspace is named `default`, not `dev`."
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
# -- so plan it as a two-step chart change. See daemons/ssh-auth/README.md.
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

# The tenant registry's keys, keyed by Terraform workspace
# (authenticated-tenant-registry D14). Generate the signing key and its JWKS
# with `caelus registry-keygen`, once per environment, and the pull HMAC key
# with:
#
#   python -c "import secrets; print(secrets.token_urlsafe(32))"
variable "registry_signing_private_keys" {
  description = "EC P-256 private key (PEM) the API and build worker sign registry tokens with, per Terraform workspace. Set in secrets.auto.tfvars."
  type        = map(string)
  sensitive   = true

  validation {
    condition     = alltrue([for k in ["default", "prod"] : contains(keys(var.registry_signing_private_keys), k)])
    error_message = "registry_signing_private_keys must have both a \"default\" (dev) and a \"prod\" key. The dev workspace is named `default`, not `dev`."
  }

  validation {
    condition = (
      !alltrue([for k in ["default", "prod"] : contains(keys(var.registry_signing_private_keys), k)])
      || var.registry_signing_private_keys["default"] != var.registry_signing_private_keys["prod"]
    )
    error_message = "The dev and prod signing keys must differ: one key for both would let a token minted in dev authorize against the prod registry."
  }
}

variable "registry_jwks" {
  description = "JWKS each environment's registry trusts, per Terraform workspace: the public half of registry_signing_private_keys as printed by `caelus registry-keygen`."
  type        = map(string)

  validation {
    condition     = alltrue([for k in ["default", "prod"] : contains(keys(var.registry_jwks), k)])
    error_message = "registry_jwks must have both a \"default\" (dev) and a \"prod\" key. The dev workspace is named `default`, not `dev`."
  }

  validation {
    condition     = alltrue([for v in values(var.registry_jwks) : can(jsondecode(v).keys)])
    error_message = "Each registry_jwks entry must be a JSON object with a \"keys\" array, as printed by `caelus registry-keygen`."
  }
}

variable "registry_pull_hmac_keys" {
  description = "Key each deployment's registry pull credential is derived from by HMAC, per Terraform workspace. Set in secrets.auto.tfvars."
  type        = map(string)
  sensitive   = true

  validation {
    condition     = alltrue([for k in ["default", "prod"] : contains(keys(var.registry_pull_hmac_keys), k)])
    error_message = "registry_pull_hmac_keys must have both a \"default\" (dev) and a \"prod\" key. The dev workspace is named `default`, not `dev`."
  }

  validation {
    condition = (
      !alltrue([for k in ["default", "prod"] : contains(keys(var.registry_pull_hmac_keys), k)])
      || var.registry_pull_hmac_keys["default"] != var.registry_pull_hmac_keys["prod"]
    )
    error_message = "The dev and prod pull HMAC keys must differ: one key for both would make a dev pull credential valid in prod."
  }
}

# The auth-path daemons' images. Immutable tags, never re-pushed, and
# deliberately not moving tags like the API's: app-auth and the SSH edge must not
# roll because the API rolled. Bump one here to deploy a new version of it.
variable "app_auth_image" {
  description = "Daemons image (daemons/) that app-auth runs from, pinned to an immutable version"
  type        = string
  default     = "ghcr.io/erikvanzijst/freepod/daemons:0.1.0"
}

variable "ssh_resolver_image" {
  description = "Daemons image (daemons/) that the SSH auth resolver runs from, pinned to an immutable version"
  type        = string
  default     = "ghcr.io/erikvanzijst/freepod/daemons:0.1.0"
}

variable "bucket_exporter_image" {
  description = "Daemons image (daemons/) that the bucket size exporter runs from, pinned to an immutable version"
  type        = string
  default     = "ghcr.io/erikvanzijst/freepod/daemons:0.2.0"
}

variable "sshpiper_port" {
  description = "Cluster-side SSH port for the SFTP entry point (null = workspace default: 2222 prod, 2223 dev)"
  type        = number
  default     = null
  nullable    = true
}

variable "s3_region" {
  description = "SigV4 signing region. Garage's default; must match tf/app/garage."
  type        = string
  default     = "garage"
}

variable "opencost_base_url" {
  description = "In-cluster OpenCost allocation API URL. Read only by the usage sampler; never Ingress-routed."
  type        = string
  default     = "http://opencost.monitoring.svc.cluster.local:9003"
}

variable "prometheus_base_url" {
  description = "In-cluster Prometheus URL. The sampler queries it for one thing only: whether OpenCost's own exporter published over a window, which /allocation cannot report -- it answers 200 with request-only numbers when the scrape is missing."
  type        = string
  default     = "http://prometheus-server.monitoring.svc.cluster.local"
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
