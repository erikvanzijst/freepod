# DNS-01 for freepod.app, whose zone is at deSEC. cert-manager has no deSEC
# solver of its own, so pr0ton11/cert-manager-desec-webhook answers the
# challenges as an aggregated API that the controller calls.

locals {
  desec_webhook_group = "acme.freepod.eu"
}

# The token's deSEC policies allow writing TXT RRsets in freepod.app and
# nothing else: no other record type, and no other zone.
resource "kubernetes_secret" "desec_api_token" {
  metadata {
    name      = "desec-token"
    namespace = "cert-manager"
  }

  data = {
    token = var.desec_api_token
  }

  type = "Opaque"

  depends_on = [helm_release.cert_manager]
}

resource "helm_release" "desec_webhook" {
  name      = "desec-webhook"
  namespace = "cert-manager"

  repository = "oci://ghcr.io/pr0ton11/helm"
  chart      = "cert-manager-desec-webhook"
  version    = var.desec_webhook_chart_version

  values = [yamlencode({
    groupName = local.desec_webhook_group
    # The only Secret the webhook may read.
    secretName = [kubernetes_secret.desec_api_token.metadata[0].name]
    image = {
      tag = var.desec_webhook_image
    }
    resources = {
      requests = { cpu = "10m", memory = "32Mi" }
      limits   = { memory = "128Mi" }
    }
  })]

  depends_on = [helm_release.cert_manager]
}
