resource "helm_release" "opencost" {
  name      = "opencost"
  namespace = var.namespace
  # Direct .tgz URL rather than `repository` + bare chart name, for the reason
  # spelled out in ../prometheus/prometheus.tf. Bump the version in the URL on
  # upgrade (latest: https://github.com/opencost/opencost-helm-chart/releases).
  chart = "https://github.com/opencost/opencost-helm-chart/releases/download/opencost-2.5.32/opencost-2.5.32.tgz"

  # https://github.com/opencost/opencost-helm-chart/blob/main/charts/opencost/values.yaml
  values = [
    yamlencode({
      # OpenCost's cost model is a two-stage pipeline: it publishes its own
      # `container_cpu_allocation` / `container_memory_allocation_bytes`
      # (max(request, usage) per container per minute) and its /allocation API
      # reads those back out of Prometheus. Unscraped, cpuCoreHours silently
      # degrades to requests only.
      service = {
        annotations = {
          "prometheus.io/scrape" = "true"
          "prometheus.io/port"   = "9003"
        }
      }

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

        # Priced as if Freepod ran on Hetzner rather than on the aging NUC it
        # actually runs on, so the numbers model what scaling out would cost.
        # Basis: CCX33 (8 dedicated vCPU, 32 GiB, EUR 138.49/mo ex VAT, Hetzner
        # price list of 15 June 2026). CCX33 is where EUR/vCPU bottoms out at
        # 17.31, down from 21.50 on CCX13/23 and flat above it.
        #
        # Hetzner sells bundles and their line-up scales RAM with vCPU exactly,
        # so list prices cannot be decomposed into per-CPU and per-RAM rates.
        # These keep OpenCost's own CPU:RAM weighting and rescale it to the
        # CCX33 price level: rate = opencost_default * 138.49 / (730 * (0.031611
        # * 8 + 0.004237 * 32)).
        #
        # UNITS: CPU per vCPU-hour, RAM per GiB-hour, storage per GB-hour
        # (Hetzner Volumes at EUR 0.0572/GB/month). Egress is 0 because EU plans
        # include 20 TB and we are nowhere near it.
        #
        # OpenCost has no notion of currency: the dashboard renders these as
        # dollars, and they are euros.
        customPricing = {
          enabled = true
          costModel = {
            description           = "Hetzner CCX33 equivalent, EUR ex VAT, June 2026"
            CPU                   = "0.015437"
            RAM                   = "0.002069"
            storage               = "0.00007836"
            GPU                   = "0"
            zoneNetworkEgress     = "0"
            regionNetworkEgress   = "0"
            internetNetworkEgress = "0"
          }
        }
      }
    })
  ]
}
