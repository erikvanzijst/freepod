resource "helm_release" "prometheus" {
  name      = "prometheus"
  namespace = var.namespace
  # Referenced by direct .tgz URL rather than `repository` + `chart = "prometheus"`
  # ON PURPOSE: the helm provider's LocateChart runs os.Stat("prometheus") relative
  # to the Terraform root (tf/deps) BEFORE hitting the repo, finds THIS module's own
  # directory (tf/deps/prometheus), and fails with "Chart.yaml file is missing". A
  # URL is not a local path, so it downloads cleanly. Do NOT revert to repository +
  # bare chart name. On version bump: change the URL AND reconcile
  # scrape_configs.yaml (forked from this chart version).
  chart = "https://github.com/prometheus-community/helm-charts/releases/download/prometheus-27.20.0/prometheus-27.20.0.tgz"

  values = [
    yamlencode({
      alertmanager = {
        enabled = true
        config = {
          global = {
            # Deliver via the in-cluster mailer relay (tf/deps/mailer). The relay
            # holds the real upstream SMTP credentials, so no auth/TLS is needed
            # on this hop and no external SMTP secrets live in this module.
            smtp_smarthost   = "smtp.mailer.svc.cluster.local:25"
            smtp_from        = "no-reply@freepod.eu"
            smtp_require_tls = false
          }
          route = {
            receiver        = "email-notifications"
            group_by        = ["alertname", "job"]
            group_wait      = "30s"
            group_interval  = "5m"
            repeat_interval = "12h"
          }
          receivers = [
            {
              name = "email-notifications"
              email_configs = [
                {
                  to            = var.alert_email_to
                  send_resolved = true
                }
              ]
            }
          ]
        }
      }

      # NOTE: the disable key is the SUBCHART name `prometheus-pushgateway`, not
      # `pushgateway` — the latter is silently ignored and the pushgateway
      # deploys anyway. We don't use pushgateway (no batch jobs pushing metrics).
      "prometheus-pushgateway" = {
        enabled = false
      }

      kube-state-metrics = {
        # Scraped by the static `prometheus-kube-state-metrics` job only. The
        # annotation would add a second copy of every series to
        # kubernetes-service-endpoints, where OpenCost's kube_* copies live too.
        prometheusScrape = false

        # KSM emits no `*_labels` metric at all unless the keys are allowlisted
        # (opt-in since KSM 2.0). The reconciler sets these; see
        # app/network_policy.py. One series per namespace.
        metricLabelsAllowlist = [
          "namespaces=[caelus.dev/tenant,caelus.dev/deployment-id,caelus.dev/owner-id,caelus.dev/product,caelus.dev/environment]"
        ]
      }

      prometheus-node-exporter = {
        enabled = true
        # https://github.com/rfmoz/grafana-dashboards?tab=readme-ov-file#node-exporter-full
        extraArgs = ["--collector.systemd", "--collector.processes"]

        # Needed by systemd collector:
        extraHostVolumeMounts = [
          {
            name      = "dbus"
            hostPath  = "/var/run/dbus"
            mountPath = "/var/run/dbus"
            readOnly  = true
          }
        ]
        # AppArmor: allow D-Bus communication
        podAnnotations = {
          "container.apparmor.security.beta.kubernetes.io/node-exporter" = "unconfined"
        }
      }

      server = {
        # ClusterIP only — Prometheus is not exposed via ingress; reach it with
        # `kubectl -n monitoring port-forward svc/prometheus-server 9090:80`.
        service = {
          type = "ClusterIP"
        }

        retention = "10d"

        global = {
          # 60s (up from 30s) to halve sample-ingest and scrape CPU on this
          # dense single-node k3s cluster. The two intentional `*-slow` jobs in
          # scrape_configs.yaml pin their own 5m interval; every other job
          # inherits this global. Note: keep dashboard/alert rate() windows >=4m
          # so they still span multiple samples at this interval.
          scrape_interval = "60s"
          scrape_timeout  = "10s"
        }
      }

      extraScrapeConfigs = yamlencode(concat([
        {
          job_name = "prometheus-kube-state-metrics"
          static_configs = [{
            targets = ["prometheus-kube-state-metrics.${var.namespace}.svc.cluster.local:8080"]
          }]
        }
        ], length(var.ceph_mgr_targets) == 0 ? [] : [
        {
          # Every manager host: only the active one returns samples, a standby
          # answers 200 with an empty body, so failover needs no reconfiguration.
          job_name       = "ceph"
          static_configs = [{ targets = var.ceph_mgr_targets }]
        }
      ]))

      # See: https://www.giffgaff.io/tech/monitoring-kubernetes-jobs
      serverFiles = {
        # Override the chart's default scrape_configs to drop high-cardinality
        # control-plane histograms and to source container usage from the
        # kubelet's resource endpoint (see scrape_configs.yaml header). Helm deep-
        # merges this map, so the chart's rule_files/alerting defaults under
        # prometheus.yml are preserved; only the scrape_configs list is replaced.
        "prometheus.yml" = {
          scrape_configs = yamldecode(file("${path.module}/scrape_configs.yaml"))
        }

        "recording_rules.yml" = {
          groups = [
            {
              name = "cronjob-latest-status"
              rules = [
                {
                  record = "job:kube_job_status_start_time:max"
                  expr   = <<-EOT
                    label_replace(
                      label_replace(
                        max(
                          kube_job_status_start_time{job="prometheus-kube-state-metrics"}
                          * ON(job_name,namespace) GROUP_RIGHT()
                          kube_job_owner{job="prometheus-kube-state-metrics", owner_name!=""}
                        )
                        BY (job_name, owner_name, namespace)
                        == ON(owner_name) GROUP_LEFT()
                        max(
                          kube_job_status_start_time{job="prometheus-kube-state-metrics"}
                          * ON(job_name,namespace) GROUP_RIGHT()
                          kube_job_owner{job="prometheus-kube-state-metrics", owner_name!=""}
                        )
                        BY (owner_name),
                      "job", "$1", "job_name", "(.+)"),
                    "cronjob", "$1", "owner_name", "(.+)")
                    EOT
                },
                {
                  record = "job:kube_job_status_failed:sum"
                  expr   = <<-EOT
                    clamp_max(
                      job:kube_job_status_start_time:max,1)
                      * ON(job) GROUP_LEFT()
                      label_replace(
                        label_replace(
                          (kube_job_status_failed{job="prometheus-kube-state-metrics"} != 0),
                          "job", "$1", "job_name", "(.+)"),
                        "cronjob", "$1", "owner_name", "(.+)")
                    EOT
                }
              ]
            }
          ]
        }
        "alerting_rules.yml" = {
          groups = [
            {
              name = "kubernetes-basic-alerts"
              rules = [

                # Node down. node-exporter is scraped by the `kubernetes-service-
                # endpoints` job (not a `node-exporter` job — that selector matched
                # nothing and the alert could never fire), so target it by the
                # node-exporter service label instead.
                {
                  alert = "NodeDown"
                  expr  = "up{service=\"prometheus-prometheus-node-exporter\"} == 0"
                  for   = "1m"
                  labels = {
                    severity = "critical"
                  }
                  annotations = {
                    summary     = "Node down"
                    description = "Node {{ $labels.instance }} is unreachable"
                  }
                },

                # High memory usage (80%)
                {
                  alert = "HighMemoryUsage"
                  expr  = "(node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) / node_memory_MemTotal_bytes > 0.8"
                  for   = "2m"
                  labels = {
                    severity = "warning"
                  }
                  annotations = {
                    summary     = "High memory usage"
                    description = "Node {{ $labels.instance }} is using >80% of memory"
                  }
                },

                # Pod in CrashLoopBackOff
                {
                  alert = "PodCrashLooping"
                  expr  = "kube_pod_container_status_waiting_reason{job='prometheus-kube-state-metrics', reason='CrashLoopBackOff'} > 0"
                  for   = "2m"
                  labels = {
                    severity = "warning"
                  }
                  annotations = {
                    summary     = "Pod crash looping"
                    description = "Pod {{ $labels.pod }} in namespace {{ $labels.namespace }} is crash looping"
                  }
                },

                # local-path reports the node's filesystem for every claim, so
                # only classes that enforce a claim's size are watched.
                {
                  alert = "VolumeFillingUp"
                  expr  = <<-EOT
                    kubelet_volume_stats_available_bytes{job="kubernetes-nodes"}
                    / kubelet_volume_stats_capacity_bytes{job="kubernetes-nodes"} < 0.15
                    and on (namespace, persistentvolumeclaim)
                    kube_persistentvolumeclaim_info{job="prometheus-kube-state-metrics", storageclass!="local-path"}
                    EOT
                  for   = "15m"
                  labels = {
                    severity = "warning"
                  }
                  annotations = {
                    summary     = "Volume filling up"
                    description = "Claim {{ $labels.persistentvolumeclaim }} in namespace {{ $labels.namespace }} has {{ $value | humanizePercentage }} free"
                  }
                },
                {
                  alert = "BackupTooOld"
                  expr  = <<-EOT
                    time() - velero_backup_last_successful_timestamp{schedule="velero-nightly"} > 26 * 3600
                    or absent(velero_backup_last_successful_timestamp{schedule="velero-nightly"})
                    EOT
                  for   = "30m"
                  labels = {
                    severity = "critical"
                  }
                  annotations = {
                    summary     = "No successful nightly backup"
                    description = "The last successful nightly Velero backup is more than 26 hours old, or Velero reports none."
                  }
                }
              ]
            },
            {
              # The SSH edge. Its availability is the resolver's: sshpiperd
              # gets both the route and the authentication decision from the
              # resolver on every connection, so a resolver that is not ready
              # is an edge that admits nobody.
              #
              # Keyed on container readiness rather than on the pod restarting,
              # because the failure that matters most does not restart
              # anything: the resolver alive and unable to reach the platform
              # database. It answers grpc.health.v1 from a real query for
              # exactly that reason, and the container's readiness probe calls
              # it (tf/app/sshpiper).
              #
              # A client presenting an unregistered key never reaches this.
              # Refusals are the resolver working, and leave it SERVING.
              name = "ssh-edge-alerts"
              rules = [
                {
                  alert = "SshResolverNotReady"
                  expr  = <<-EOT
                    kube_pod_container_status_ready{job="prometheus-kube-state-metrics", container="ssh-resolver"} == 0
                    EOT
                  for   = "2m"
                  labels = {
                    severity = "critical"
                  }
                  annotations = {
                    summary     = "SSH auth resolver not ready"
                    description = "The SSH auth resolver in {{ $labels.namespace }} ({{ $labels.pod }}) is not ready. SFTP access to every deployment in that environment is refused while this holds; the resolver reports unready when it cannot read the platform database."
                  }
                },
                {
                  # The edge with no resolver at all: sshpiperd calls
                  # ListCallbacks at startup and exits if it fails, so a
                  # missing resolver takes the whole pod with it.
                  alert = "SshEdgeDown"
                  expr  = <<-EOT
                    kube_deployment_status_replicas_available{job="prometheus-kube-state-metrics", deployment="sshpiper"} == 0
                    EOT
                  for   = "2m"
                  labels = {
                    severity = "critical"
                  }
                  annotations = {
                    summary     = "SSH edge down"
                    description = "The sshpiperd deployment in {{ $labels.namespace }} has no available replica. The environment's public SSH port is not being served."
                  }
                }
              ]
            },
            {
              # The external Ceph cluster. Three hosts, three copies: one host
              # down is survivable but leaves no spare copy, and a pool that
              # reaches its quota fails every write into it.
              name = "ceph-alerts"
              rules = [
                {
                  alert = "CephMetricsAbsent"
                  expr  = "absent(ceph_health_status)"
                  for   = "5m"
                  labels = {
                    severity = "critical"
                  }
                  annotations = {
                    summary     = "No Ceph metrics"
                    description = "Prometheus has no ceph_health_status: the cluster's active manager is unreachable or its prometheus module is off. Ceph itself may be fine, but nothing below can fire."
                  }
                },
                {
                  alert = "CephHealthError"
                  expr  = "ceph_health_status == 2"
                  for   = "5m"
                  labels = {
                    severity = "critical"
                  }
                  annotations = {
                    summary     = "Ceph HEALTH_ERR"
                    description = "Ceph reports HEALTH_ERR. Check `ceph health detail` on a storage node."
                  }
                },
                {
                  alert = "CephHealthCheck"
                  expr  = "ceph_health_detail == 1"
                  for   = "15m"
                  labels = {
                    severity = "warning"
                  }
                  annotations = {
                    summary     = "Ceph health check {{ $labels.name }}"
                    description = "Ceph health check {{ $labels.name }} ({{ $labels.severity }}) has been active for 15 minutes."
                  }
                },
                {
                  alert = "CephMonQuorumAtRisk"
                  expr  = "count(ceph_mon_quorum_status == 1) < count(ceph_mon_metadata)"
                  for   = "5m"
                  labels = {
                    severity = "critical"
                  }
                  annotations = {
                    summary     = "Ceph monitor out of quorum"
                    description = "{{ $value }} monitors are in quorum. Losing one more stops all Ceph IO."
                  }
                },
                {
                  alert = "CephOSDDown"
                  expr  = "count(ceph_osd_up == 0) > 0"
                  for   = "5m"
                  labels = {
                    severity = "critical"
                  }
                  annotations = {
                    summary     = "Ceph OSD down"
                    description = "{{ $value }} OSD(s) down. Data is served from the remaining copies; another failure stops IO on the affected placement groups."
                  }
                },
                {
                  alert = "CephPGsInactive"
                  expr  = "sum(ceph_pg_total) - sum(ceph_pg_active) > 0"
                  for   = "5m"
                  labels = {
                    severity = "critical"
                  }
                  annotations = {
                    summary     = "Ceph placement groups inactive"
                    description = "{{ $value }} placement groups are not active. IO to the volumes on them blocks."
                  }
                },
                {
                  # Ahead of Ceph's own nearfull (85%): with one OSD per host,
                  # recovery has no other OSD in the host to spill onto.
                  alert = "CephOSDNearlyFull"
                  expr  = "ceph_osd_stat_bytes_used / ceph_osd_stat_bytes > 0.75"
                  for   = "15m"
                  labels = {
                    severity = "warning"
                  }
                  annotations = {
                    summary     = "Ceph OSD {{ $labels.ceph_daemon }} over 75% full"
                    description = "{{ $labels.ceph_daemon }} is {{ $value | humanizePercentage }} full. Ceph stops writes cluster-wide at 95%."
                  }
                },
                {
                  alert = "CephPoolQuotaNearlyFull"
                  expr  = "(ceph_pool_stored / (ceph_pool_quota_bytes > 0)) * on(pool_id) group_left(name) ceph_pool_metadata > 0.8"
                  for   = "15m"
                  labels = {
                    severity = "warning"
                  }
                  annotations = {
                    summary     = "Ceph pool {{ $labels.name }} over 80% of its quota"
                    description = "Pool {{ $labels.name }} stores {{ $value | humanizePercentage }} of its quota. At 100% every write to its volumes fails."
                  }
                },
                {
                  alert = "CephPoolQuotaFull"
                  expr  = "(ceph_pool_stored / (ceph_pool_quota_bytes > 0)) * on(pool_id) group_left(name) ceph_pool_metadata > 0.95"
                  for   = "5m"
                  labels = {
                    severity = "critical"
                  }
                  annotations = {
                    summary     = "Ceph pool {{ $labels.name }} at its quota"
                    description = "Pool {{ $labels.name }} stores {{ $value | humanizePercentage }} of its quota. Raise it (`ceph osd pool set-quota`) or free space before writes fail."
                  }
                }
              ]
            },
            {
              name = "job-alerts"
              rules = [
                {
                  alert = "CronJobFailed"
                  expr  = <<-EOT
                    job:kube_job_status_failed:sum
                    * ON(cronjob,namespace) GROUP_LEFT()
                    (kube_cronjob_spec_suspend{job="prometheus-kube-state-metrics"} == 0)
                    EOT
                  for   = "2m"
                  labels = {
                    severity = "critical"
                  }
                  annotations = {
                    summary     = "CronJob failure"
                    description = "The most recent CronJob '{{ $labels.job_name }}' in namespace '{{ $labels.namespace }}' failed and has no successful run after."
                  }
                }
              ]
            }
          ]
        }
      }
    })
  ]
}
