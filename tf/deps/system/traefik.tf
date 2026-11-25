# Freepod's ingress controller is a self-managed Traefik Helm release (./helm/traefik).
module "traefik" {
  source                          = "./helm/traefik"
  floating_ipv4                   = var.floating_ipv4
  ipv6_relay_source_ips           = var.ipv6_relay_source_ips
  default_tls_resources_namespace = var.default_tls_resources_namespace
}
