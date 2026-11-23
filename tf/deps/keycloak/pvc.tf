resource "kubernetes_persistent_volume_claim" "postgres_pvc" {
  metadata {
    name      = "postgres-pvc"
    namespace = var.namespace
  }

  wait_until_bound = false

  spec {
    access_modes = ["ReadWriteOnce"]
    resources {
      requests = {
        storage = "1Gi"
      }
    }
  }
}


resource "kubernetes_persistent_volume_claim" "postgres_data" {
  metadata {
    name      = "postgres-data"
    namespace = var.namespace
  }

  spec {
    access_modes       = ["ReadWriteOncePod"]
    storage_class_name = var.storage_class
    resources {
      requests = {
        storage = "5Gi"
      }
    }
  }
}
