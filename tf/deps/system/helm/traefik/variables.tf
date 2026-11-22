variable "haproxy_edge_ip" {
  description = "IP/CIDR of the homelab HAProxy edge, trusted for PROXY protocol on the web/websecure entrypoints."
  type        = string
}

variable "ipv6_relay_source_ip" {
  description = "IPv4 address/CIDR the IPv6 relay connects to Traefik from, trusted for PROXY protocol on the web/websecure entrypoints."
  type        = string
}

# Upgrading: tenants' HTTP access logs (api/app/services/http_logs.py) select a
# deployment's requests by Traefik's Ingress router names, which this version
# writes as `<namespace>-<ingress>-<host+path>@kubernetes`. A release that names
# routers differently leaves `freepod log --http` empty, so check it after a bump.
variable "traefik_chart_version" {
  description = "Upstream Traefik Helm chart version. 42.4.1 ships Traefik app v3.7.19. v3.7 is the floor: providers.kubernetesCRD.defaultTLSResourcesNamespace is rejected by v3.6. Chart 42.4 validates values against a closed schema and moved service.type to service.spec.type."
  type        = string
  default     = "42.4.1"
}

variable "default_tls_resources_namespace" {
  description = "Namespace Traefik reads the `default` TLSStore and TLSOption from. Pinning it is what makes the store's move between namespaces gapless: a store named `default` outside this namespace is ignored, where an unpinned Traefik refuses every one it finds and serves its self-signed certificate to the whole fleet instead."
  type        = string
}
