# klipper's hostPorts are IPv4-only, so the node's IPv6 ports are relayed from the host network.
# Web traffic dials the Traefik pods directly: through a Service or hostPort the node's own
# connections are masqueraded to 10.42.0.1, too broad to trust for PROXY protocol.

locals {
  labels = {
    app = "ipv6-relay"
  }

  config = templatefile("${path.module}/haproxy.cfg.tftpl", {
    traefik_host = "${kubernetes_service.traefik.metadata[0].name}.${var.traefik_namespace}.svc.cluster.local"
    web_ports    = var.web_ports
    ssh_ports    = var.ssh_ports
  })
}

resource "kubernetes_service" "traefik" {
  metadata {
    name      = "traefik-pods"
    namespace = var.traefik_namespace
  }

  spec {
    cluster_ip = "None"
    selector   = var.traefik_selector
  }
}

resource "kubernetes_config_map" "config" {
  metadata {
    name      = "ipv6-relay"
    namespace = var.namespace
  }

  data = {
    "haproxy.cfg" = local.config
  }
}

resource "kubernetes_daemonset" "relay" {
  metadata {
    name      = "ipv6-relay"
    namespace = var.namespace
    labels    = local.labels
  }

  spec {
    selector {
      match_labels = local.labels
    }

    template {
      metadata {
        labels = local.labels
        annotations = {
          "checksum/config" = sha256(local.config)
        }
      }

      spec {
        host_network                    = true
        dns_policy                      = "ClusterFirstWithHostNet"
        node_selector                   = var.node_selector
        automount_service_account_token = false
        enable_service_links            = false

        container {
          name  = "haproxy"
          image = var.image
          args  = ["-f", "/usr/local/etc/haproxy/haproxy.cfg"]

          env {
            name = "HOST_IP"
            value_from {
              field_ref {
                field_path = "status.hostIP"
              }
            }
          }

          resources {
            requests = {
              cpu    = "10m"
              memory = "32Mi"
            }
            limits = {
              memory = "128Mi"
            }
          }

          security_context {
            run_as_user                = 0
            allow_privilege_escalation = false
            read_only_root_filesystem  = true
            capabilities {
              drop = ["ALL"]
              add  = ["NET_BIND_SERVICE"]
            }
          }

          volume_mount {
            name       = "config"
            mount_path = "/usr/local/etc/haproxy"
            read_only  = true
          }
        }

        volume {
          name = "config"
          config_map {
            name = kubernetes_config_map.config.metadata[0].name
          }
        }
      }
    }
  }
}
