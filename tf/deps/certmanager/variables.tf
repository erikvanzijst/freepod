variable "cloudflare_api_token" {
  description = "Cloudflare API token with edit rights on the freepod.eu DNS zone (DNS-01 wildcard issuance)."
  type        = string
  sensitive   = true
}

variable "desec_api_token" {
  description = "deSEC API token with write access to TXT RRsets in the freepod.app zone only (DNS-01 issuance)."
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

variable "desec_webhook_chart_version" {
  description = "Chart version of pr0ton11/cert-manager-desec-webhook. Bump it together with desec_webhook_image, after reviewing the release's source."
  type        = string
  default     = "0.1.6"
}

variable "desec_webhook_image" {
  description = "Webhook image tag and digest. The digest is the one the release's tag build pushed; pinning it keeps a re-pushed tag from reaching the cluster."
  type        = string
  default     = "0.1.6@sha256:94ba9a05ca396f0000cfee0b1d064a67eef376732b83db0b4fb9a004a0d4fb6f"
}
