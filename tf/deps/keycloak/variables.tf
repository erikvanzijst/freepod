variable "namespace" {
  description = "Namespace to deploy into"
  type = string
}

variable "domain" {
  description = "The base domain name of Caelus (e.g. app.deprutser.be)"
  type = string
}

variable "keycloak_admin_password" {
  description = "Keycloak admin password (use secrets.auto.tfvars)"
  type        = string
  sensitive   = true
}

variable "keycloak_image" {
  description = "Keycloak container image with the Freepod theme baked in (see keycloak/Dockerfile). Tagged <Keycloak version>-<build>, pushed by `scripts/build-images.sh <tag> --keycloak`; a tag is never re-pushed, so every theme or base change takes the next build number."
  type        = string
  default     = "ghcr.io/erikvanzijst/freepod/keycloak:26.8.1-4"
}
