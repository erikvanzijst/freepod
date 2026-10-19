variable "cloudflare_api_token" {
  description = "Cloudflare API token with edit rights on the freepod.eu DNS zone (DNS-01 wildcard issuance)."
  type        = string
  sensitive   = true
}

variable "letsencrypt_email" {
  description = "ACME account email for the Let's Encrypt ClusterIssuers."
  type        = string
}

variable "chart_version" {
  description = "cert-manager Helm chart version (== app version). Upgrade one minor version at a time, to the latest patch of each, as cert-manager's upgrade guide asks."
  type        = string
  default     = "v1.21.2"
}
