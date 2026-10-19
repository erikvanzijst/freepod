# cert-manager on the freepod cluster. Installs CRDs and runs in its own
# `cert-manager` namespace.
resource "helm_release" "cert_manager" {
  name             = "cert-manager"
  namespace        = "cert-manager"
  create_namespace = true

  repository = "https://charts.jetstack.io"
  chart      = "cert-manager"
  version    = var.chart_version

  # Helm leaves CRDs marked keep in place on uninstall, so removing the release
  # never deletes every Certificate in the cluster with them.
  set {
    name  = "crds.enabled"
    value = "true"
  }
  set {
    name  = "crds.keep"
    value = "true"
  }
}
