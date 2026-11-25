# Freepod's ingress controller: a self-managed Traefik Helm release.
#
# This replaces the previous approach of amending the k3s-bundled Traefik via a
# HelmChartConfig (retired tf/deps/system/traefik.tf). That object was also defined by a
# stray host manifest (/var/lib/rancher/k3s/server/manifests/traefik-config.yaml), which
# k3s's `deploy` addon controller replayed on every k3s restart — reverting the Terraform
# config and breaking freepod.eu TLS (see openspec/changes/selfmanaged-traefik). The bundled
# Traefik is now disabled on the node (/etc/rancher/k3s/config.yaml `disable: [traefik]`), so
# Terraform is the single source of truth.
resource "helm_release" "traefik" {
  name             = "traefik"
  namespace        = "kube-system"
  create_namespace = false

  repository = "https://traefik.github.io/charts"
  chart      = "traefik"
  version    = var.traefik_chart_version

  # Stopped deployments rely on two kubernetesIngress settings (deployment-power-
  # reconciliation spec): allowExternalNameServices, set in the values, carries
  # their hostname to the parking page; and the chart's default
  # allowEmptyServices: true makes a router whose Service has no ready endpoints
  # answer 503 instead of 404. Kept here rather than in the values file, where a
  # comment would change the release's values.
  values = [
    templatefile("${path.module}/values.yaml.tftpl", {
      floating_ipv4                   = var.floating_ipv4
      ipv6_relay_source_ips           = var.ipv6_relay_source_ips
      default_tls_resources_namespace = var.default_tls_resources_namespace
    })
  ]
}
