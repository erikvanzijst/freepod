resource "kubernetes_deployment" "echo" {
  metadata {
    name      = "echo"
    namespace = var.namespace
    labels = {
      app = "echo"
    }
  }

  spec {
    replicas = 1

    selector {
      match_labels = {
        app = "echo"
      }
    }

    template {
      metadata {
        labels = {
          app = "echo"
        }
      }

      spec {
        container {
          name  = "echo"
          image = "mendhak/http-https-echo"

          port {
            container_port = 8080
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      spec[0].template[0].metadata[0].annotations["kubectl.kubernetes.io/restartedAt"],
    ]
  }
}

resource "kubernetes_service" "echo" {
  metadata {
    name      = "echo"
    namespace = var.namespace
  }

  spec {
    selector = {
      app = "echo"
    }

    port {
      port        = 8080
      target_port = 8080
    }
  }
}
