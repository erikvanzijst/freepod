# The tenant PostgreSQL cluster: one shared server holding every `custom`
# deployment's own database, per Terraform workspace so dev and prod tenants
# never share one (design D14).
#
# Deliberately NOT `caelus-postgres`. That instance holds the platform's own
# tables in a 256Mi limit under a `Recreate` strategy; a tenant sharing it could
# take the platform down with one query.
#
# Tenants never reach this Service. They reach the pooler (tenant-pooler.tf),
# which the tenant NetworkPolicy permits and this port does not.

resource "random_password" "tenant_db_superuser" {
  length  = 32
  special = false
}

# The non-superuser role every long-running platform process uses. CREATEDB and
# CREATEROLE plus two predefined roles cover the whole lifecycle; only the
# bootstrap ever connects as superuser (design D6).
resource "random_password" "tenant_db_admin" {
  length  = 32
  special = false
}

# The pooler's auth_query role. Read by both the bootstrap (which sets it on the
# role) and the pooler (which authenticates with it), so it is generated once
# here rather than configured twice.
resource "random_password" "tenant_db_pgbouncer_auth" {
  length  = 32
  special = false
}

# The metrics sidecar's read-only role (pg_monitor).
resource "random_password" "tenant_db_exporter" {
  length  = 32
  special = false
}

# Superuser plus the role passwords the bootstrap assigns. Separate from
# `caelus-tenant-db` below, which the API and worker *containers* read: the
# superuser password belongs only to the PostgreSQL container and to the
# bootstrap init container, which is the whole point of D6's blast-radius
# argument.
resource "kubernetes_secret" "tenant_db_bootstrap" {
  metadata {
    name      = "caelus-tenant-db-bootstrap"
    namespace = var.namespace
  }

  type = "Opaque"

  data = {
    POSTGRES_PASSWORD       = random_password.tenant_db_superuser.result
    CAELUS_ADMIN_PASSWORD   = random_password.tenant_db_admin.result
    PGBOUNCER_AUTH_PASSWORD = random_password.tenant_db_pgbouncer_auth.result
    # Also read by the sidecar, by key, so it never sees the superuser's.
    POSTGRES_EXPORTER_PASSWORD = random_password.tenant_db_exporter.result
  }
}

# What the API and workers hold: the admin credential and the addresses, in one
# Secret for the same reason `caelus-s3` carries its endpoint alongside its key
# — there is no way to rotate the credential and leave a stale host behind.
#
# The admin connects to PostgreSQL directly, not through the pooler: `SET ROLE`
# followed by an owner-scoped `ALTER DATABASE` is session state, which is
# exactly what transaction pooling does not preserve.
resource "kubernetes_secret" "tenant_db" {
  metadata {
    name      = "caelus-tenant-db"
    namespace = var.namespace
  }

  type = "Opaque"

  data = {
    CAELUS_TENANT_DB_HOST           = "caelus-tenant-postgres.${var.namespace}.svc.cluster.local"
    CAELUS_TENANT_DB_PORT           = "5432"
    CAELUS_TENANT_DB_ADMIN_USER     = "caelus_admin"
    CAELUS_TENANT_DB_ADMIN_PASSWORD = random_password.tenant_db_admin.result
    CAELUS_TENANT_DB_MAINTENANCE_DB = "postgres"
  }
}

# Sized against design D13's self-imposed 10 GB budget, which is what this
# number means: `local-path` enforces no volume size and cannot expand one, so
# the declared capacity is documentation and the real ceiling is the node's own
# disk. Physical safety rests on monitoring node free space, never on this.
resource "kubernetes_persistent_volume_claim" "tenant_db_pvc" {
  metadata {
    name      = "caelus-tenant-db-pvc"
    namespace = var.namespace
  }

  wait_until_bound = false

  spec {
    access_modes = ["ReadWriteOnce"]
    resources {
      requests = {
        storage = "10Gi"
      }
    }
  }
}

# The bootstrap, as plain SQL in the repository rather than as a `caelus`
# command: it is cluster setup, so it is expressed as infrastructure and reads
# as SQL in review (design D6).
#
# Not /docker-entrypoint-initdb.d/, which fires exactly once -- the image guards
# it on an empty data directory, so the bootstrap could never be changed or
# repaired without destroying every tenant database, and a skipped script logs
# nothing at all.
resource "kubernetes_config_map" "tenant_db_bootstrap" {
  metadata {
    name      = "caelus-tenant-db-bootstrap"
    namespace = var.namespace
  }

  data = {
    "tenant-bootstrap.sql" = file("${path.module}/tenant-bootstrap.sql")
  }
}

resource "kubernetes_deployment" "tenant_db" {
  metadata {
    name      = "caelus-tenant-postgres"
    namespace = var.namespace
    labels = {
      app = "caelus-tenant-postgres"
    }
  }

  spec {
    replicas = 1

    selector {
      match_labels = {
        app = "caelus-tenant-postgres"
      }
    }

    # One PVC, one writer: never two pods on the same data directory.
    strategy {
      type = "Recreate"
    }

    template {
      metadata {
        labels = {
          app = "caelus-tenant-postgres"
        }
      }

      spec {
        container {
          image = local.tenant_db_image
          name  = "postgres"

          # Design D13, worst case ~1.3 GB against the 2Gi limit below. The
          # ceiling is deliberately well under the limit: under-dimensioning CPU
          # is slow, under-dimensioning memory has the OOM killer take the
          # database out.
          args = [
            "-c", "shared_buffers=256MB",
            "-c", "max_connections=100",
            "-c", "superuser_reserved_connections=5",
            # PG16+. Keeps a slot for pgbouncer_auth (which holds
            # pg_use_reserved_connections) when tenants have taken the rest, so
            # a full cluster cannot also break authentication.
            "-c", "reserved_connections=3",
            "-c", "work_mem=4MB",
            "-c", "maintenance_work_mem=64MB",
            "-c", "autovacuum_max_workers=3",
          ]

          env {
            name = "POSTGRES_PASSWORD"
            value_from {
              secret_key_ref {
                name = kubernetes_secret.tenant_db_bootstrap.metadata[0].name
                key  = "POSTGRES_PASSWORD"
              }
            }
          }

          port {
            name           = "postgres"
            container_port = 5432
            protocol       = "TCP"
          }

          # PostgreSQL 18 moved PGDATA to /var/lib/postgresql/18/docker and the
          # image's VOLUME up to /var/lib/postgresql. Mounting the old
          # /var/lib/postgresql/data would leave the data directory on the
          # pod's ephemeral filesystem -- an empty cluster after every restart.
          volume_mount {
            name       = "tenant-db-data"
            mount_path = "/var/lib/postgresql"
          }

          resources {
            requests = {
              memory = "512Mi"
              cpu    = "100m"
            }
            limits = {
              memory = "2Gi"
              cpu    = "400m"
            }
          }

          liveness_probe {
            exec {
              command = ["pg_isready", "-U", "postgres"]
            }
            initial_delay_seconds = 30
            period_seconds        = 10
            timeout_seconds       = 5
            failure_threshold     = 3
          }

          readiness_probe {
            exec {
              command = ["pg_isready", "-U", "postgres"]
            }
            initial_delay_seconds = 5
            period_seconds        = 5
            timeout_seconds       = 3
            failure_threshold     = 3
          }
        }

        # Publishes per-database sizes (pg_database_size_bytes{datname}) and
        # server statistics to Prometheus, for usage metering.
        #
        # A sidecar shares the pod's readiness: if this container is not
        # running, the pod leaves the Service above and every tenant loses its
        # database.
        container {
          image = local.tenant_db_exporter_image
          name  = "postgres-exporter"

          env {
            name  = "DATA_SOURCE_URI"
            value = "localhost:5432/postgres?sslmode=disable"
          }

          env {
            name  = "DATA_SOURCE_USER"
            value = "postgres_exporter"
          }

          env {
            name = "DATA_SOURCE_PASS"
            value_from {
              secret_key_ref {
                name = kubernetes_secret.tenant_db_bootstrap.metadata[0].name
                key  = "POSTGRES_EXPORTER_PASSWORD"
              }
            }
          }

          port {
            name           = "metrics"
            container_port = 9187
            protocol       = "TCP"
          }

          resources {
            requests = {
              memory = "32Mi"
              cpu    = "10m"
            }
            limits = {
              memory = "128Mi"
              cpu    = "100m"
            }
          }
        }

        volume {
          name = "tenant-db-data"
          persistent_volume_claim {
            claim_name = kubernetes_persistent_volume_claim.tenant_db_pvc.metadata[0].name
          }
        }
      }
    }
  }
}

resource "kubernetes_service" "tenant_db" {
  metadata {
    name      = "caelus-tenant-postgres"
    namespace = var.namespace
  }

  spec {
    selector = {
      app = "caelus-tenant-postgres"
    }

    port {
      name        = "postgres"
      port        = 5432
      target_port = "postgres"
    }
  }
}

resource "kubernetes_service" "tenant_db_metrics" {
  metadata {
    name      = "caelus-tenant-postgres-metrics"
    namespace = var.namespace
    annotations = {
      "prometheus.io/scrape" = "true"
      "prometheus.io/port"   = "9187"
    }
  }

  spec {
    selector = {
      app = "caelus-tenant-postgres"
    }

    port {
      name        = "metrics"
      port        = 9187
      target_port = "metrics"
    }
  }
}
