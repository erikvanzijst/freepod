# PgBouncer: the only path a tenant pod has to its database.
#
# Two instances behind one ClusterIP Service, which is a pure capacity decision
# because nothing in this design issues a pooler admin command -- suspension is
# role state on the server, provisioning writes no pooler configuration, and
# there is deliberately no `admin_users` here for anything to connect to
# (design D9).
#
# Two consequences of running two, each a trap otherwise: server connections
# multiply by instance count, so `default_pool_size x 2` is what lands on the
# server's `max_connections`; and every client-side limit is per instance, so
# `max_user_connections = 25` permits 50 fleet-wide.

resource "kubernetes_config_map" "tenant_pooler" {
  metadata {
    name      = "caelus-tenant-pooler-config"
    namespace = var.namespace
  }

  data = {
    "pgbouncer.ini" = <<-EOT
      # Wildcard routing: one entry serves every tenant database, so
      # provisioning a deployment needs no pooler reload and no restart.
      [databases]
      * = host=caelus-tenant-postgres port=5432

      [pgbouncer]
      listen_addr = 0.0.0.0
      listen_port = 6432

      # Credentials are resolved by querying the server, so adding a tenant
      # requires no file change. auth_file below holds one entry: the role
      # doing the querying.
      auth_type = scram-sha-256
      auth_file = /etc/pgbouncer/userlist.txt
      auth_user = pgbouncer_auth
      auth_query = SELECT uname, phash FROM pgbouncer.user_lookup($1)

      # Pinned, and pinned *here* rather than at the tenant's own database for
      # two reasons: unpinned, the lookup runs inside the database the client
      # asked for -- which its tenant owns and can create objects in -- and the
      # SECURITY DEFINER function would need installing into every database.
      # `postgres` has CONNECT revoked from PUBLIC by the bootstrap, so no
      # tenant can reach it.
      auth_dbname = postgres

      pool_mode = transaction
      # PgBouncer >= 1.21. Without it, every driver that prepares statements by
      # default fails at runtime with a confusing error.
      max_prepared_statements = 100
      max_client_conn = 500
      default_pool_size = 3
      max_db_connections = 5
      max_user_connections = 25
      server_idle_timeout = 60

      # Sent by libpq and JDBC on connect; harmless, and fatal to the
      # connection if the pooler refuses to ignore them.
      ignore_startup_parameters = extra_float_digits,options
    EOT
  }
}

# One line, one role: the identity the pooler itself uses to run auth_query.
# Every tenant credential arrives through that query instead, which is why this
# file never changes as the fleet grows.
resource "kubernetes_secret" "tenant_pooler_auth" {
  metadata {
    name      = "caelus-tenant-pooler-auth"
    namespace = var.namespace
  }

  type = "Opaque"

  data = {
    "userlist.txt" = "\"pgbouncer_auth\" \"${random_password.tenant_db_pgbouncer_auth.result}\"\n"
  }
}

resource "kubernetes_deployment" "tenant_pooler" {
  metadata {
    name      = "caelus-tenant-pooler"
    namespace = var.namespace
    labels = {
      app = local.tenant_pooler_app_label
    }
  }

  spec {
    replicas = 2

    selector {
      match_labels = {
        app = local.tenant_pooler_app_label
      }
    }

    strategy {
      type = "RollingUpdate"
      rolling_update {
        max_surge       = 1
        max_unavailable = 0
      }
    }

    template {
      metadata {
        labels = {
          app = local.tenant_pooler_app_label
        }
        annotations = {
          "checksum/config" = sha256(jsonencode(kubernetes_config_map.tenant_pooler.data))
          # PgBouncer reads userlist.txt at startup. Without this the rotated
          # password would sit in the Secret while every instance kept
          # authenticating with the old one.
          "checksum/auth" = sha256(random_password.tenant_db_pgbouncer_auth.result)
        }
      }

      spec {
        container {
          image = local.tenant_pooler_image
          name  = "pgbouncer"

          port {
            name           = "pgbouncer"
            container_port = 6432
            protocol       = "TCP"
          }

          volume_mount {
            name       = "config"
            mount_path = "/etc/pgbouncer/pgbouncer.ini"
            sub_path   = "pgbouncer.ini"
            read_only  = true
          }

          volume_mount {
            name       = "auth"
            mount_path = "/etc/pgbouncer/userlist.txt"
            sub_path   = "userlist.txt"
            read_only  = true
          }

          resources {
            requests = {
              memory = "32Mi"
              cpu    = "10m"
            }
            limits = {
              memory = "128Mi"
              cpu    = "50m"
            }
          }

          liveness_probe {
            tcp_socket {
              port = "6432"
            }
            initial_delay_seconds = 10
            period_seconds        = 10
            failure_threshold     = 3
          }

          readiness_probe {
            tcp_socket {
              port = "6432"
            }
            initial_delay_seconds = 3
            period_seconds        = 5
            failure_threshold     = 3
          }
        }

        volume {
          name = "config"
          config_map {
            name = kubernetes_config_map.tenant_pooler.metadata[0].name
          }
        }

        volume {
          name = "auth"
          secret {
            secret_name = kubernetes_secret.tenant_pooler_auth.metadata[0].name
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

resource "kubernetes_service" "tenant_pooler" {
  metadata {
    name      = "caelus-tenant-pooler"
    namespace = var.namespace
  }

  spec {
    selector = {
      app = local.tenant_pooler_app_label
    }

    port {
      name        = "pgbouncer"
      port        = 6432
      target_port = "pgbouncer"
    }
  }
}
