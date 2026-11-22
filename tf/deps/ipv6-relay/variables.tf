variable "namespace" {
  type = string
}

variable "image" {
  type    = string
  default = "haproxy:3.4.8-alpine"
}

variable "node_selector" {
  description = "The node whose public IPv6 address the DNS AAAA records name."
  type        = map(string)
  default = {
    "node-role.kubernetes.io/control-plane" = "true"
  }
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

variable "web_ports" {
  description = "Public IPv6 port => Traefik container port. Relayed with PROXY protocol v2 from the node's IPv4 address, which Traefik must trust."
  type        = map(number)
  default = {
    80  = 8000
    443 = 8443
  }
}

variable "ssh_ports" {
  description = "Public IPv6 port => node port sshpiper's klipper LoadBalancer binds. Relayed without PROXY protocol."
  type        = map(number)
}
