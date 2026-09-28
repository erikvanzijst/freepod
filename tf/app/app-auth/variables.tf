variable "namespace" {
  description = "Namespace app-auth runs in: this environment's login namespace, beside oauth2-proxy."
  type        = string
}

variable "domain" {
  description = "Environment domain; the broker is served on login.<domain>."
  type        = string
}

variable "image" {
  description = "app-auth image, pinned to an immutable version from app-auth/VERSION."
  type        = string
}

variable "database_url" {
  description = "libpq URL connecting as the caelus_app_auth role."
  type        = string
  sensitive   = true
}

variable "oidc_issuer" {
  description = "Keycloak realm issuer URL."
  type        = string
}

variable "oidc_client_id" {
  description = "This environment's freepod-apps-* client ID."
  type        = string
}

variable "oidc_client_secret" {
  description = "This environment's freepod-apps-* client secret."
  type        = string
  sensitive   = true
}
