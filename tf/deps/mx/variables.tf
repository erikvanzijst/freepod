variable "namespace" {
  description = "Namespace to deploy into"
  type        = string
}

variable "image" {
  description = "Maddy container image"
  type        = string
  default     = "foxcpp/maddy:0.9.7"
}

variable "hostname" {
  description = "Public name of the MX, the target of the domain's MX record"
  type        = string
}

variable "domain" {
  description = "Domain to accept mail for"
  type        = string
}

variable "account" {
  description = "The one mailbox every recipient in the domain is delivered to; also its IMAP username"
  type        = string
}

variable "password_hash" {
  description = "The account's IMAP password hash, as printed by `maddy hash`"
  type        = string
  sensitive   = true
}

variable "cluster_issuer" {
  description = "cert-manager ClusterIssuer for the MX certificate"
  type        = string
  default     = "letsencrypt-dns"
}

variable "storage_class" {
  description = "StorageClass of the mailbox volume"
  type        = string
}

variable "storage_size" {
  description = "Size of the mailbox volume"
  type        = string
  default     = "5Gi"
}

variable "monitoring_namespace" {
  description = "Namespace Prometheus scrapes from"
  type        = string
}

variable "traefik_namespace" {
  type    = string
  default = "kube-system"
}

variable "traefik_selector" {
  type = map(string)
  default = {
    "app.kubernetes.io/name"     = "traefik"
    "app.kubernetes.io/instance" = "traefik-kube-system"
  }
}

variable "pod_cidrs" {
  description = "The cluster's pod network, where Traefik's PROXY protocol connections come from."
  type        = list(string)
  default     = ["10.42.0.0/16"]
}
