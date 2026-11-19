locals {
  chunks_cache_mb  = 512
  results_cache_mb = 128

  memcached_resources = {
    for mb in [local.chunks_cache_mb, local.results_cache_mb] : mb => {
      requests = { cpu = "50m", memory = "${floor((mb * 12 + 5) / 10)}Mi" }
      limits   = { memory = "${floor((mb * 12 + 5) / 10)}Mi" }
    }
  }
}

resource "helm_release" "loki" {
  name       = "loki"
  namespace  = var.namespace
  repository = "oci://ghcr.io/grafana-community/helm-charts"
  chart      = "loki"
  version    = "21.4.1"

  # https://github.com/grafana-community/helm-charts/blob/main/charts/loki/values.yaml
  values = [
    yamlencode({
      # https://grafana.com/docs/loki/latest/setup/install/helm/install-monolithic/
      deploymentMode = "Monolithic"
      singleBinary = {
        replicas = 1
        persistence = {
          enabled = true
          size    = "10Gi"
        }
      }
      loki = {
        auth_enabled = false
        commonConfig = {
          replication_factor = 1
        }
        schemaConfig = {
          configs = [{
            from         = "2025-10-01"
            object_store = "filesystem"
            store        = "tsdb"
            schema       = "v13"
            index = {
              prefix = "index_"
              period = "24h"
            }
          }]
        }
        pattern_ingester = {
          enabled = true
        }
        # Retention. Until this was set, nothing was ever deleted: the
        # compactor already runs in-process (`-target=all`, `/services`
        # reports `compactor => Running`), but without `retention_enabled`
        # it only compacts indexes and never deletes. The top-level
        # `compactor.replicas` below is inert in SingleBinary mode -- the
        # chart only renders a compactor StatefulSet when deploymentMode is
        # Distributed -- so do not raise it to "run the compactor"; that
        # would start a second one competing over the same filesystem store.
        #
        # `delete_request_store` is not optional: Loki refuses to start
        # with `compactor.delete-request-store should be configured when
        # retention is enabled`.
        compactor = {
          retention_enabled    = true
          delete_request_store = "filesystem"
        }
        # 336h = 14 days, derived from measured ingest against a 3 GiB budget
        # for the log store on this hardware (the volume is 10Gi; the cap is
        # the operator's, not the volume's, and rises when the node does).
        #
        #   measured 2026-08-18, platform logs only:
        #     chunks on disk   373 MB over a 20-day-old PVC ->  18.7 MB/day
        #     ingest           3.14 GB over 17.0 days       -> 185 MB/day raw
        #
        #   3072 MiB / (18.7 MB/day * 14 d) = 11.7x
        #
        # So 14 days holds ~262 MB at today's rate and stays inside 3 GiB
        # until tenant applications push total ingest to ~12x the platform
        # baseline. Tenant output is the new and unmeasured load -- this is
        # sized to survive it, not to promise users a history depth.
        # Re-derive from the same two numbers before changing it.
        limits_config = {
          retention_period = "336h"
        }
        storage = {
          type = "filesystem"
        }
        ui = {
          enabled = true
        }
      }
      # Shrink the memcached caches from their multi-node chart defaults
      # (chunks 8192MB, results 1024MB) to homelab scale. The defaults
      # hold nearly the entire ~10Gi log store in RAM.
      #
      # Without `resources` the chart requests a fixed 500m CPU per cache, for
      # a memcached that idles at a few millicores. Setting `resources`
      # replaces the chart's whole computed block, so the memory request and
      # limit repeat its formula: round(allocatedMemory * 1.2) MiB.
      chunksCache = {
        allocatedMemory = local.chunks_cache_mb
        resources       = local.memcached_resources[local.chunks_cache_mb]
      }
      resultsCache = {
        allocatedMemory = local.results_cache_mb
        resources       = local.memcached_resources[local.results_cache_mb]
      }

      # The gateway's required anti-affinity forbids two gateways per node, and
      # the only other node is the tainted build node, so a rolling update's
      # surge pod can never schedule. Replace it instead.
      gateway = {
        deploymentStrategy = {
          type = "Recreate"
        }
      }

      # Zero out replica counts of other deployment modes:
      backend = {
        replicas = 0
      }
      read = {
        replicas = 0
      }
      write = {
        replicas = 0
      }
      ingester = {
        replicas = 0
      }
      querier = {
        replicas = 0
      }
      queryFrontend = {
        replicas = 0
      }
      queryScheduler = {
        replicas = 0
      }
      distributor = {
        replicas = 0
      }
      compactor = {
        replicas = 0
      }
      indexGateway = {
        replicas = 0
      }
      bloomGateway = {
        replicas = 0
      }
    })
  ]
}

resource "helm_release" "alloy" {
  name       = "alloy"
  repository = "https://grafana.github.io/helm-charts"
  chart      = "alloy"
  version    = "1.16.0"
  namespace  = var.namespace

  values = [
    yamlencode({
      crds = {
        create = false
      }
      global = {
        podSecurityContext = {
          runAsUser  = 0
          runAsGroup = 0
        }
      }
      alloy = {
        configMap = {
          content = file("${path.module}/config.alloy")
        }
        enableReporting = false
        storagePath     = "/var/lib/alloy"
        securityContext = {
          allowPrivilegeEscalation = false
          readOnlyRootFilesystem   = true
          capabilities = {
            drop = ["ALL"]
          }
        }
        mounts = {
          extra = [
            {
              name      = "pods"
              mountPath = "/var/log/pods"
              readOnly  = true
            },
            {
              name      = "storage"
              mountPath = "/var/lib/alloy"
            },
          ]
        }
      }
      controller = {
        # Every node, tainted node pools included.
        tolerations = [
          {
            operator = "Exists"
            effect   = "NoSchedule"
          }
        ]
        volumes = {
          extra = [
            {
              name     = "pods"
              hostPath = { path = "/var/log/pods" }
            },
            {
              name     = "storage"
              hostPath = { path = "/var/lib/alloy", type = "DirectoryOrCreate" }
            },
          ]
        }
      }
    })
  ]
}
