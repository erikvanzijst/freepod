variable "floating_ipv4" {
  description = "The floating IPv4 address (keepalived on the server VMs), served by Traefik like its LoadBalancer IP."
  type        = string
}

variable "haproxy_edge_ip" {
  description = "IP/CIDR of the homelab HAProxy edge, trusted for PROXY protocol on the web/websecure entrypoints."
  type        = string
}

variable "ipv6_relay_source_ips" {
  description = "IPv4 addresses/CIDRs the IPv6 relays connect to Traefik from, trusted for PROXY protocol on the web/websecure entrypoints."
  type        = list(string)
}

variable "default_tls_resources_namespace" {
  description = "Namespace Traefik reads the `default` TLSStore from. Flipping it is the store's cutover between namespaces."
  type        = string
}
