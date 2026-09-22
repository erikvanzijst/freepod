resource "helm_release" "opencost" {
  name      = "opencost"
  namespace = var.namespace
  # latest: https://github.com/opencost/opencost-helm-chart/releases)
  chart = "https://github.com/opencost/opencost-helm-chart/releases/download/opencost-2.5.32/opencost-2.5.32.tgz"

  # https://github.com/opencost/opencost-helm-chart/blob/main/charts/opencost/values.yaml
  values = [
    yamlencode({
      opencost = {
        prometheus = {
          internal = {
            enabled     = true
            serviceName = "prometheus-server"
            # Prometheus runs in this same namespace; the chart defaults to
            # `prometheus-system`.
            namespaceName = var.namespace
            port          = 80
            scheme        = "http"
          }
        }

        # Chart defaults are GCP us-central1 list prices, so every cost field is
        # fiction on this hardware. The resource fields the allocation API
        # returns -- cpuCoreHours, ramByteHours, the usage/request/limit
        # averages -- are independent of pricing, and are the ones we care about
        # for usage accounting.
        customPricing = {
          enabled = false
        }
      }
    })
  ]
}
