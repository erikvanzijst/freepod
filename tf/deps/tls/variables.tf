variable "namespace" {
  description = "Platform TLS namespace: holds the store, the platform wildcard's secret, and every account certificate."
  type        = string
  default     = "caelus-tls"
}

variable "cluster_issuer" {
  description = "DNS-01 ClusterIssuer for the platform wildcard. Switch to `letsencrypt-dns-staging` only while rebuilding this from scratch — a staging default certificate is untrusted for the whole fleet."
  type        = string
  default     = "letsencrypt-dns"
}

variable "wildcard_dns_names" {
  description = "Names the platform wildcard covers. Changing this set issues a new certificate against the weekly allowance."
  type        = list(string)
  default = [
    "freepod.eu",
    "*.freepod.eu",
    "*.dev.freepod.eu",
  ]
}
