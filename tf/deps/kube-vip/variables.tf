variable "namespace" {
  type    = string
  default = "kube-system"
}

variable "addresses" {
  description = "The floating addresses, at most one IPv4 and one IPv6, for the API server and ingress. The IPv4 one must be outside the LAN's DHCP range and in every server's tls-san."
  type        = list(string)
}

variable "interface" {
  description = "The server nodes' LAN interface, which carries the addresses."
  type        = string
  default     = "eth0"
}

variable "image" {
  type    = string
  default = "ghcr.io/kube-vip/kube-vip:v1.3.2"
}
