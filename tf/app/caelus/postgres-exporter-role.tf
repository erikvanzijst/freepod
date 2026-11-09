# The platform database's metrics sidecar (postgres.tf). Its role is created by
# postgres-exporter-bootstrap.sql in the worker's init containers; until then
# the sidecar reports pg_up 0 and retries on every scrape.
resource "random_password" "postgres_exporter" {
  length  = 32
  special = false
}

resource "kubernetes_secret" "postgres_exporter" {
  metadata {
    name      = "caelus-postgres-exporter"
    namespace = var.namespace
  }

  type = "Opaque"

  data = {
    POSTGRES_EXPORTER_PASSWORD = random_password.postgres_exporter.result
  }
}

resource "kubernetes_config_map" "postgres_exporter_bootstrap" {
  metadata {
    name      = "caelus-postgres-exporter-bootstrap"
    namespace = var.namespace
  }

  data = {
    "postgres-exporter-bootstrap.sql" = file("${path.module}/postgres-exporter-bootstrap.sql")
  }
}
