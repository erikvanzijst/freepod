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
  description = "cert-manager Helm chart version (== app version). Matches the homelab (v1.17.2), which issues the identical apex+wildcard freepod cert cleanly via Cloudflare DNS-01."
  type        = string
  default     = "v1.17.2"
}
