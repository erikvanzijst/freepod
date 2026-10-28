locals {
  labels = {
    app = "mx"
  }

  config = templatefile("${path.module}/maddy.conf.tftpl", {
    hostname = var.hostname
    domain   = var.domain
    account  = var.account
  })

  maddy = "maddy -config /etc/maddy/config/maddy.conf"
}

resource "kubernetes_manifest" "certificate" {
  manifest = {
    apiVersion = "cert-manager.io/v1"
    kind       = "Certificate"
    metadata = {
      name      = "mx"
      namespace = var.namespace
    }
    spec = {
      secretName = "mx-tls"
      issuerRef = {
        name = var.cluster_issuer
        kind = "ClusterIssuer"
      }
      dnsNames = [var.hostname]
    }
  }
}

resource "kubernetes_config_map" "config" {
  metadata {
    name      = "mx-config"
    namespace = var.namespace
  }

  data = {
    "maddy.conf" = local.config
  }
}

resource "kubernetes_secret" "passwd" {
  metadata {
    name      = "mx-passwd"
    namespace = var.namespace
  }

  data = {
    passwd = "${var.account}: ${var.password_hash}\n"
  }
}

resource "kubernetes_service" "headless" {
  metadata {
    name      = "mx-headless"
    namespace = var.namespace
  }

  spec {
    cluster_ip = "None"
    selector   = local.labels
  }
}

resource "kubernetes_stateful_set" "mx" {
  metadata {
    name      = "mx"
    namespace = var.namespace
    labels    = local.labels
  }

  spec {
    replicas     = 1
    service_name = kubernetes_service.headless.metadata[0].name

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
        # The router forwards :25 and :993 to this node, and the Service's
        # Local traffic policy only answers on the node running the pod.
        node_selector = {
          "node-role.kubernetes.io/control-plane" = "true"
        }

        security_context {
          run_as_user     = 1000
          run_as_group    = 1000
          run_as_non_root = true
          fs_group        = 1000
          seccomp_profile {
            type = "RuntimeDefault"
          }
        }

        # Delivery to a mailbox that does not exist is refused, so the account
        # must exist before the first message arrives, not on first IMAP login.
        init_container {
          name    = "create-account"
          image   = var.image
          command = ["sh", "-c", "${local.maddy} imap-acct list 2>/dev/null | grep -qxF \"$ACCOUNT\" || ${local.maddy} imap-acct create \"$ACCOUNT\""]

          env {
            name  = "ACCOUNT"
            value = var.account
          }

          security_context {
            allow_privilege_escalation = false
            read_only_root_filesystem  = true
            capabilities {
              drop = ["ALL"]
            }
          }

          volume_mount {
            name       = "data"
            mount_path = "/data"
          }
          volume_mount {
            name       = "config"
            mount_path = "/etc/maddy/config"
          }
          volume_mount {
            name       = "tls"
            mount_path = "/etc/maddy/tls"
          }
          volume_mount {
            name       = "passwd"
            mount_path = "/etc/maddy/secret"
          }
          volume_mount {
            name       = "tmp"
            mount_path = "/tmp"
          }
        }

        container {
          name  = "maddy"
          image = var.image
          args  = ["-config", "/etc/maddy/config/maddy.conf", "run"]

          port {
            name           = "smtp"
            container_port = 2525
          }
          port {
            name           = "imaps"
            container_port = 9993
          }
          port {
            name           = "metrics"
            container_port = 9749
          }

          # Not a TCP probe on the SMTP port: Maddy logs every dropped
          # connection, which would put a line in the log every period.
          readiness_probe {
            http_get {
              path = "/metrics"
              port = "metrics"
            }
            period_seconds = 10
          }

          resources {
            requests = {
              cpu    = "10m"
              memory = "32Mi"
            }
            limits = {
              memory = "256Mi"
            }
          }

          security_context {
            allow_privilege_escalation = false
            read_only_root_filesystem  = true
            capabilities {
              drop = ["ALL"]
            }
          }

          volume_mount {
            name       = "data"
            mount_path = "/data"
          }
          volume_mount {
            name       = "config"
            mount_path = "/etc/maddy/config"
          }
          volume_mount {
            name       = "tls"
            mount_path = "/etc/maddy/tls"
          }
          volume_mount {
            name       = "passwd"
            mount_path = "/etc/maddy/secret"
          }
          volume_mount {
            name       = "tmp"
            mount_path = "/tmp"
          }
        }

        volume {
          name = "config"
          config_map {
            name = kubernetes_config_map.config.metadata[0].name
          }
        }
        # Maddy re-reads the certificate every minute, so renewals need no restart.
        volume {
          name = "tls"
          secret {
            secret_name = "mx-tls"
          }
        }
        volume {
          name = "passwd"
          secret {
            secret_name = kubernetes_secret.passwd.metadata[0].name
          }
        }
        volume {
          name = "tmp"
          empty_dir {}
        }
      }
    }

    volume_claim_template {
      metadata {
        name = "data"
      }
      spec {
        access_modes       = ["ReadWriteOnce"]
        storage_class_name = "local-path"
        resources {
          requests = {
            storage = var.storage_size
          }
        }
      }
    }
  }

  depends_on = [kubernetes_manifest.certificate]
}

# A klipper LoadBalancer owns the node's host :25 and :993. Local keeps the
# sender's address intact for the SPF and DMARC checks.
resource "kubernetes_service" "mx" {
  metadata {
    name      = "mx"
    namespace = var.namespace
  }

  spec {
    type                    = "LoadBalancer"
    external_traffic_policy = "Local"
    selector                = local.labels

    port {
      name        = "smtp"
      port        = 25
      target_port = "smtp"
    }
    port {
      name        = "imaps"
      port        = 993
      target_port = "imaps"
    }
  }
}

resource "kubernetes_service" "metrics" {
  metadata {
    name      = "mx-metrics"
    namespace = var.namespace
    annotations = {
      "prometheus.io/scrape" = "true"
      "prometheus.io/port"   = "9749"
    }
  }

  spec {
    selector = local.labels

    port {
      name        = "metrics"
      port        = 9749
      target_port = "metrics"
    }
  }
}

resource "kubernetes_network_policy" "mx" {
  metadata {
    name      = "mx-ingress"
    namespace = var.namespace
  }

  spec {
    pod_selector {
      match_labels = local.labels
    }
    policy_types = ["Ingress"]

    ingress {
      ports {
        port     = "2525"
        protocol = "TCP"
      }
      ports {
        port     = "9993"
        protocol = "TCP"
      }
    }

    ingress {
      from {
        namespace_selector {
          match_labels = {
            "kubernetes.io/metadata.name" = var.monitoring_namespace
          }
        }
      }
      ports {
        port     = "9749"
        protocol = "TCP"
      }
    }
  }
}
