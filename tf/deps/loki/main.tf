resource "helm_release" "loki" {
  name      = "loki"
  namespace = var.namespace
  # Bump the version in the URL on upgrade (latest:
  # https://github.com/grafana/loki/blob/main/production/helm/loki/Chart.yaml).
  chart = "https://github.com/grafana/helm-charts/releases/download/helm-loki-6.41.1/loki-6.41.1.tgz"

  # https://github.com/grafana/loki/blob/main/production/helm/loki/values.yaml
  values = [
    yamlencode({
      # https://grafana.com/docs/loki/latest/setup/install/helm/install-monolithic/
      deploymentMode = "SingleBinary"
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
        # `delete_request_store` is not optional: Loki 3.5.5 refuses to start
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
      # hold nearly the entire ~10Gi log store in RAM; the chart sets the
      # pod's memory request/limit to allocatedMemory * ~1.2. Reclaims ~7.7Gi RAM.
      chunksCache = {
        allocatedMemory = 512
      }
      resultsCache = {
        allocatedMemory = 128
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
      bloomCompactor = {
        replicas = 0
      }
      bloomGateway = {
        replicas = 0
      }
    })
  ]
}

resource "helm_release" "promtail" {
  name       = "promtail"
  repository = "https://grafana.github.io/helm-charts"
  chart      = "promtail"
  version    = "6.17.0" # check latest version at https://github.com/grafana/helm-charts/blob/main/charts/promtail/Chart.yaml
  namespace  = var.namespace

  values = [
    yamlencode({
      # Every node, tainted pools included (the build node is
      # caelus.dev/node-pool=builds:NoSchedule). Replaces the chart's default
      # list, which tolerates only the control-plane taints.
      tolerations = [
        {
          operator = "Exists"
          effect   = "NoSchedule"
        }
      ]
      config = {
        server = {
          http_listen_port = 9080
          grpc_listen_port = 0
        }
        clients = [
          {
            url = "http://loki.${var.namespace}.svc.cluster.local:3100/loki/api/v1/push"
          }
        ]

        # Helpful example: https://github.com/grafana/loki/issues/4381
        snippets = {
          scrapeConfigs = <<-EOT
            - job_name: kubernetes-pods
              pipeline_stages:
                - cri: {}
                # Parse Traefik CLF access logs (kube-system/traefik) so the
                # upstream app is queryable. Non-access lines (Traefik's own
                # app logs) simply don't match the regex and pass through untouched.
                - match:
                    selector: '{namespace="kube-system", container="traefik"}'
                    stages:
                      - regex:
                          expression: '^(?P<remote_addr>\S+) - (?P<remote_user>\S+) \[(?P<time_local>[^\]]+)\] "(?P<method>\S+) (?P<path>\S+) (?P<protocol>[^"]+)" (?P<status>\d{3}) (?P<bytes>\d+) "(?P<referer>[^"]*)" "(?P<user_agent>[^"]*)" (?P<request_count>\d+) "(?P<router>[^"]*)" "(?P<upstream>[^"]*)" (?P<duration>\S+)$'
                      # Low-cardinality fields -> stream labels (queryable/cheap)
                      - labels:
                          method:
                          status:
                          router:
                      # High-cardinality fields -> structured metadata (queryable
                      # without exploding stream cardinality; needs v13 schema)
                      - structured_metadata:
                          remote_addr:
                          path:
                          user_agent:
                          upstream:
                          duration:
              kubernetes_sd_configs:
                - role: pod
              relabel_configs:
                - source_labels:
                    - __meta_kubernetes_pod_controller_name
                  regex: ([0-9a-z-.]+?)(-[0-9a-f]{8,10})?
                  action: replace
                  target_label: __tmp_controller_name
                - source_labels:
                    - __meta_kubernetes_pod_label_app_kubernetes_io_name
                    - __meta_kubernetes_pod_label_app
                    - __tmp_controller_name
                    - __meta_kubernetes_pod_name
                  regex: ^;*([^;]+)(;.*)?$
                  action: replace
                  target_label: app
                - source_labels:
                    - __meta_kubernetes_pod_label_app_kubernetes_io_instance
                    - __meta_kubernetes_pod_label_instance
                  regex: ^;*([^;]+)(;.*)?$
                  action: replace
                  target_label: instance
                # Promote the platform's per-rollout pod label to a stream
                # label, so one release's output is an index lookup rather
                # than a scan of everything the deployment ever wrote. The
                # release id is constant within a pod and `pod` is already a
                # stream label, so this widens each series without creating
                # new ones. A pod without the label does not match the regex,
                # so no `release_id` is set and it collects exactly as before
                # -- which is every platform and system pod, and every tenant
                # pod from a chart that does not render the label.
                # `caelus.dev/release-id` -> `caelus_dev_release_id`.
                - source_labels:
                    - __meta_kubernetes_pod_label_caelus_dev_release_id
                  regex: ^;*([^;]+)(;.*)?$
                  action: replace
                  target_label: release_id
                - source_labels:
                    - __meta_kubernetes_pod_label_app_kubernetes_io_component
                    - __meta_kubernetes_pod_label_component
                  regex: ^;*([^;]+)(;.*)?$
                  action: replace
                  target_label: component
                - action: replace
                  source_labels:
                  - __meta_kubernetes_pod_node_name
                  target_label: node_name
                - action: replace
                  source_labels:
                  - __meta_kubernetes_namespace
                  target_label: namespace
                - action: replace
                  replacement: $1
                  separator: /
                  source_labels:
                  - namespace
                  - app
                  target_label: job
                - action: replace
                  source_labels:
                  - __meta_kubernetes_pod_name
                  target_label: pod
                - action: replace
                  source_labels:
                  - __meta_kubernetes_pod_container_name
                  target_label: container
                - action: replace
                  replacement: /var/log/pods/*$1/*.log
                  separator: /
                  source_labels:
                  - __meta_kubernetes_pod_uid
                  - __meta_kubernetes_pod_container_name
                  target_label: __path__
                - action: replace
                  regex: true/(.*)
                  replacement: /var/log/pods/*$1/*.log
                  separator: /
                  source_labels:
                  - __meta_kubernetes_pod_annotationpresent_kubernetes_io_config_hash
                  - __meta_kubernetes_pod_annotation_kubernetes_io_config_hash
                  - __meta_kubernetes_pod_container_name
                  target_label: __path__
          EOT
        }
      }
    })
  ]
}
