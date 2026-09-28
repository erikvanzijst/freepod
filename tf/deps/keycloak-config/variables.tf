variable "realm_name" {
  description = "Name of the Freepod end-user realm. End users live here, never in `master` (Keycloak's administrative realm)."
  type        = string
  default     = "freepod"
}

variable "prod_domain" {
  description = "Public hostname of the production Freepod environment, served by the freepod-prod client."
  type        = string
  default     = "freepod.eu"
}

variable "dev_domain" {
  description = "Public hostname of the development Freepod environment, served by the freepod-dev client."
  type        = string
  default     = "dev.freepod.eu"
}

variable "grafana_domain" {
  description = "Public hostname for Grafana, served by the grafana client. Keep in sync with prometheus/variables.tf."
  type        = string
  default     = "grafana.freepod.eu"
}

variable "smtp_host" {
  description = "SMTP endpoint for realm email. Defaults to the in-cluster mailer relay, which holds the upstream credentials."
  type        = string
  default     = "smtp.mailer.svc.cluster.local"
}

variable "smtp_port" {
  description = "Port for the SMTP endpoint. The relay listens on plain 25 inside the cluster."
  type        = string
  default     = "25"
}

variable "smtp_from" {
  description = "Envelope/header From address for realm email."
  type        = string
  default     = "noreply@freepod.eu"
}

variable "smtp_from_display_name" {
  description = "Display name shown alongside the From address."
  type        = string
  default     = "Freepod"
}

variable "smtp_reply_to" {
  description = "Reply-To address for realm email."
  type        = string
  default     = "noreply@freepod.eu"
}

variable "google_client_id" {
  description = "Client ID of the Google OAuth web client used by the Google identity provider."
  type        = string
}

variable "google_client_secret" {
  description = "Client secret of the Google OAuth web client used by the Google identity provider."
  type        = string
  sensitive   = true
}
