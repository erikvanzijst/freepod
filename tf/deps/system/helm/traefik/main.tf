# Freepod's ingress controller: a self-managed Traefik Helm release.
#
# This replaces the previous approach of amending the k3s-bundled Traefik via a
# HelmChartConfig (retired tf/deps/system/traefik.tf). That object was also defined by a
# stray host manifest (/var/lib/rancher/k3s/server/manifests/traefik-config.yaml), which
# k3s's `deploy` addon controller replayed on every k3s restart — reverting the Terraform
# config and breaking freepod.eu TLS (see openspec/changes/selfmanaged-traefik). The bundled
# Traefik is now disabled on the node (/etc/rancher/k3s/config.yaml `disable: [traefik]`), so
# Terraform is the single source of truth.
#
# Unlike homelab's Traefik (ClusterIP behind an in-cluster HAProxy), freepod's Traefik is
# reached by the homelab HAProxy edge across clusters at the node's HOST :80/:443, so the
# Service is a klipper LoadBalancer (see values.yaml.tftpl).
resource "helm_release" "traefik" {
  name             = "traefik"
  namespace        = "kube-system"
  create_namespace = false

  repository = "https://traefik.github.io/charts"
  chart      = "traefik"
  version    = var.traefik_chart_version

  values = [
    templatefile("${path.module}/values.yaml.tftpl", {
      haproxy_edge_ip                 = var.haproxy_edge_ip
      default_tls_resources_namespace = var.default_tls_resources_namespace
    })
  ]
}
