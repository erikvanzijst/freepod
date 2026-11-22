# Freepod's ingress controller is a self-managed Traefik Helm release (./helm/traefik).
module "traefik" {
  source                          = "./helm/traefik"
  haproxy_edge_ip                 = var.haproxy_edge_ip
  ipv6_relay_source_ip            = var.ipv6_relay_source_ip
  default_tls_resources_namespace = var.default_tls_resources_namespace
}
