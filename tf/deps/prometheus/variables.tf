variable "namespace" {
  description = "Namespace to deploy into"
  type        = string
}

variable "grafana_domain" {
  description = "Public hostname for Grafana (the only externally exposed monitoring UI)."
  type        = string
  default     = "grafana.freepod.eu"
}

variable "grafana_admin_password" {
  description = "Grafana local admin password (break-glass; primary auth is Keycloak OIDC)."
  type        = string
  sensitive   = true
}

variable "alert_email_to" {
  description = "Recipient address for Alertmanager alert emails."
  type        = string
}

variable "keycloak_url" {
  description = "Base URL of the Keycloak instance."
  type        = string
  default     = "https://keycloak.freepod.eu"
}

variable "keycloak_realm" {
  description = "Keycloak realm holding the grafana client and the freepod-observability group. Not `master` — end-user identity lives in the freepod realm."
  type        = string
  default     = "freepod"
}

variable "grafana_oidc_client_id" {
  description = "Keycloak OIDC client ID for Grafana."
  type        = string
}

variable "grafana_oidc_client_secret" {
  description = "Keycloak OIDC client secret for Grafana."
  type        = string
  sensitive   = true
}

variable "ceph_mgr_targets" {
  description = "Ceph manager prometheus endpoints, `host:9283`, one per manager host. Empty skips the Ceph scrape job."
  type        = list(string)
  default     = []
}
