variable "namespace" {
  description = "Platform TLS namespace: holds the store and the platform certificate's secret."
  type        = string
  default     = "caelus-tls"
}

variable "cluster_issuer" {
  description = "DNS-01 ClusterIssuer for the platform wildcard. Switch to `letsencrypt-dns-staging` only while rebuilding this from scratch — a staging default certificate is untrusted for the whole fleet."
  type        = string
  default     = "letsencrypt-dns"
}

variable "wildcard_dns_names" {
  description = "Names the platform certificate covers, across the freepod.eu (Cloudflare) and freepod.app (deSEC) zones; the DNS-01 issuer picks the solver per zone. Changing this set issues a new certificate against the weekly allowance."
  type        = list(string)
  default = [
    "freepod.eu",
    "*.freepod.eu",
    "*.dev.freepod.eu",
    "freepod.app",
    # dev.freepod.app is covered by *.freepod.app; listing both is an order
    # Let's Encrypt rejects as redundant.
    "*.freepod.app",
    "*.dev.freepod.app",
  ]
}
