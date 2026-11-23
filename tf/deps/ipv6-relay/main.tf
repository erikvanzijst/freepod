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

  firewall_inputs = {
    interface = var.interface
    tcp_ports = sort(concat(keys(var.web_ports), keys(var.ssh_ports)))
    udp_ports = var.allowed_udp_ports
  }
  firewall_id = substr(sha256(jsonencode([file("${path.module}/ipv6-edge.nft.tftpl"), local.firewall_inputs])), 0, 16)
  firewall    = templatefile("${path.module}/ipv6-edge.nft.tftpl", merge(local.firewall_inputs, { id = local.firewall_id }))

  # The table's comment names the rules it holds, so the loop reloads only a
  # missing or outdated table and the drop counter survives.
  firewall_script = <<-EOT
    while true; do
      id=$(sed -n 's/^  comment "\(.*\)"$/\1/p' /etc/ipv6-edge/rules.nft)
      if ! nft list table ip6 freepod_edge 2>/dev/null | grep -qF "comment \"$id\""; then
        nft -f /etc/ipv6-edge/rules.nft && echo "applied table ip6 freepod_edge $id"
      fi
      sleep 60
    done
  EOT
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

resource "kubernetes_config_map" "firewall" {
  metadata {
    name      = "ipv6-edge-firewall"
    namespace = var.namespace
  }

  data = {
    "rules.nft" = local.firewall
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

        container {
          name    = "firewall"
          image   = var.firewall_image
          command = ["sh", "-c", local.firewall_script]

          resources {
            requests = {
              cpu    = "1m"
              memory = "4Mi"
            }
            limits = {
              memory = "32Mi"
            }
          }

          security_context {
            run_as_user                = 0
            allow_privilege_escalation = false
            read_only_root_filesystem  = true
            capabilities {
              drop = ["ALL"]
              add  = ["NET_ADMIN"]
            }
          }

          volume_mount {
            name       = "firewall"
            mount_path = "/etc/ipv6-edge"
            read_only  = true
          }
        }

        volume {
          name = "firewall"
          config_map {
            name = kubernetes_config_map.firewall.metadata[0].name
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

