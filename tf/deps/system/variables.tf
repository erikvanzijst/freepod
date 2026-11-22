variable "haproxy_edge_ip" {
  description = "IP/CIDR of the homelab HAProxy edge, trusted for PROXY protocol on the web/websecure entrypoints."
  type        = string
}

variable "ipv6_relay_source_ip" {
  description = "IPv4 address/CIDR the IPv6 relay connects to Traefik from, trusted for PROXY protocol on the web/websecure entrypoints."
  type        = string
}

variable "default_tls_resources_namespace" {
  description = "Namespace Traefik reads the `default` TLSStore from. Flipping it is the store's cutover between namespaces."
  type        = string
}
