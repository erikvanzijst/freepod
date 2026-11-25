variable "namespace" {
  type = string
}

variable "image" {
  type    = string
  default = "haproxy:3.4.8-alpine"
}

variable "firewall_image" {
  description = "nftables image the firewall container runs, built from ./nftables by `scripts/build-images.sh --nftables`."
  type        = string
  default     = "ghcr.io/erikvanzijst/freepod/nftables:1.1.6-1"
}

variable "interfaces" {
  description = "The node's uplink, and the VMAC keepalived puts the floating address on. The firewall drops IPv6 arriving on them unless it is a reply, ICMPv6, from a link-local or ULA source, or to a relayed port or var.allowed_udp_ports."
  type        = list(string)
  default     = ["eth0", "vrrp170"]
}

variable "allowed_udp_ports" {
  description = "UDP ports the firewall also admits on var.interfaces. 41641 is Tailscale's direct WireGuard port."
  type        = list(number)
  default     = [41641]
}

variable "node_selector" {
  description = "The node whose public IPv6 address the DNS AAAA records name."
  type        = map(string)
  default = {
    "caelus.dev/edge" = "true"
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
  description = "Public IPv6 port => host:port of an sshpiper Service. Relayed without PROXY protocol."
  type        = map(string)
}
