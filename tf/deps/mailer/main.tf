resource "kubernetes_config_map" "smtp_config" {
  metadata {
    name      = "smtp-config"
    namespace = var.namespace
  }

  data = {
    RELAY_HOST     = var.smtp_host
    RELAY_PORT     = var.smtp_port
    RELAY_USER     = var.smtp_username
    RELAY_PASSWORD = var.smtp_password
    # Longer than the 4d queue ttl, so delay warnings are never sent:
    # Purelymail refuses the null sender they use.
    OPENSMTPD_BOUNCE_WARN = "5d"
  }
}

resource "kubernetes_deployment" "smtp" {
  metadata {
    name      = "smtp"
    namespace = var.namespace
    labels = {
      app = "smtp"
    }
  }

  spec {
    replicas = 1
    selector {
      match_labels = {
        app = "smtp"
      }
    }

    template {
      metadata {
        labels = {
          app = "smtp"
        }
      }

      spec {
        container {
          name  = "smtp"
          image = "wodby/opensmtpd:latest"

          port {
            container_port = 25
          }

          env_from {
            config_map_ref {
              name = kubernetes_config_map.smtp_config.metadata[0].name
            }
          }
        }
      }
    }
  }
}

resource "kubernetes_service" "smtp_relay_service" {
  metadata {
    name      = "smtp"
    namespace = var.namespace
  }

  spec {
    selector = {
      app = "smtp"
    }

    port {
      name        = "smtp"
      port        = 25
      target_port = 25
      protocol    = "TCP"
    }

    type = "ClusterIP"
  }
}
