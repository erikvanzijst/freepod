variable "namespace" {
  description = "Namespace the registry runs in (caelus-registry / caelus-registry-dev)"
  type        = string
}

variable "image" {
  description = "Registry image, pinned: JWKS trust needs distribution v3, and the floating `registry:3` tag moves"
  type        = string
  default     = "docker.io/library/registry:3.1.1"
}

variable "kubectl_image" {
  description = "Image the weekly restart runs `kubectl rollout restart` from"
  type        = string
  default     = "registry.k8s.io/kubectl:v1.34.3"
}

variable "host" {
  description = "Name the registry is addressed by and its certificate covers; also the audience every token must name"
  type        = string
}

variable "cluster_ip" {
  description = "Pinned Service address from the service CIDR's statically reserved low band, published in DNS for the node's container runtime"
  type        = string
}

variable "token_realm" {
  description = "Token endpoint URL the registry's authentication challenge names"
  type        = string
}

variable "token_issuer" {
  description = "The one issuer the registry trusts; both token signers use it"
  type        = string
}

variable "jwks" {
  description = "JWKS (JSON) of the keys whose tokens the registry accepts, as printed by `caelus registry-keygen`"
  type        = string
}

variable "cluster_issuer" {
  description = "cert-manager ClusterIssuer for the registry's certificate. DNS-01, because the name resolves to an address nothing outside the cluster can reach."
  type        = string
  default     = "letsencrypt-dns"
}

variable "storage_size" {
  description = "Requested volume size. Nominal: local-path enforces no quota."
  type        = string
  default     = "20Gi"
}

variable "restart_schedule" {
  description = "When the registry restarts, which loads a renewed certificate and collects garbage"
  type        = string
  default     = "0 4 * * 1"
}
