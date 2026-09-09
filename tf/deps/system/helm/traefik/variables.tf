variable "haproxy_edge_ip" {
  description = "IP/CIDR of the homelab HAProxy edge, trusted for PROXY protocol on the web/websecure entrypoints."
  type        = string
}

variable "traefik_chart_version" {
  description = "Upstream Traefik Helm chart version. 41.5.0 ships Traefik app v3.7.13, raised from 39.0.5/v3.6.10 for providers.kubernetesCRD.defaultTLSResourcesNamespace, which v3.7 introduced and v3.6 rejects as an unknown field. The chart renamed two keys this release range: providers.kubernetesIngressNginx -> kubernetesIngressNGINX, and logs.{general,access} -> top-level log/accessLog."
  type        = string
  default     = "41.5.0"
}

variable "default_tls_resources_namespace" {
  description = "Namespace Traefik reads the `default` TLSStore and TLSOption from. Pinning it is what makes the store's move between namespaces gapless: a store named `default` outside this namespace is ignored, where an unpinned Traefik refuses every one it finds and serves its self-signed certificate to the whole fleet instead."
  type        = string
}
