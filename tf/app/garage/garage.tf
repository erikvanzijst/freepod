locals {
  labels = { app = "garage" }

  metadata_dir = "/var/lib/garage/meta"
  data_dir     = "/var/lib/garage/data"

  # Garage's own default. Surfaced to the Caelus API as a setting so the SigV4
  # signing region matches on both sides.
  s3_region = "garage"

  garage_toml = templatefile("${path.module}/garage.toml.tftpl", {
    metadata_dir       = local.metadata_dir
    data_dir           = local.data_dir
    s3_region          = local.s3_region
    replication_factor = 1
  })
}

# Generated rather than supplied: nothing outside this instance needs either
# value, so they live only in Terraform state, like tf/app/caelus/tenant-db.tf.
resource "random_password" "admin_token" {
  length  = 48
  special = false
}

resource "random_id" "rpc_secret" {
  byte_length = 32
}

# Neither value is ever written into the ConfigMap: both are injected into the
# process as GARAGE_RPC_SECRET / GARAGE_ADMIN_TOKEN. Garage refuses to start on
# world-readable secret files, and a ConfigMap mount is world-readable.
resource "kubernetes_secret" "garage" {
  metadata {
    name      = "garage-secrets"
    namespace = var.namespace
  }

  type = "Opaque"

  data = {
    admin_token = random_password.admin_token.result
    rpc_secret  = random_id.rpc_secret.hex
  }
}

resource "kubernetes_config_map" "garage" {
  metadata {
    name      = "garage-config"
    namespace = var.namespace
  }

  data = {
    "garage.toml" = local.garage_toml
  }
}

resource "kubernetes_stateful_set" "garage" {
  metadata {
    name      = "garage"
    namespace = var.namespace
    labels    = local.labels
  }

  spec {
    # Single node, single replica: see garage.toml.tftpl on replication_factor.
    replicas     = 1
    service_name = kubernetes_service.garage.metadata[0].name

    selector {
      match_labels = local.labels
    }

    template {
      metadata {
        labels = local.labels
        annotations = {
          # Roll the pod when the rendered config changes; a ConfigMap update
          # alone would otherwise leave the running process on the old TOML.
          "checksum/config" = sha256(local.garage_toml)
        }
      }

      spec {
        container {
          name  = "garage"
          image = var.garage_image

          port {
            name           = "s3"
            container_port = 3900
            protocol       = "TCP"
          }

          port {
            name           = "admin"
            container_port = 3903
            protocol       = "TCP"
          }

          port {
            name           = "rpc"
            container_port = 3901
            protocol       = "TCP"
          }

          env {
            name = "GARAGE_RPC_SECRET"
            value_from {
              secret_key_ref {
                name = kubernetes_secret.garage.metadata[0].name
                key  = "rpc_secret"
              }
            }
          }

          env {
            name = "GARAGE_ADMIN_TOKEN"
            value_from {
              secret_key_ref {
                name = kubernetes_secret.garage.metadata[0].name
                key  = "admin_token"
              }
            }
          }

          volume_mount {
            name       = "config"
            mount_path = "/etc/garage.toml"
            sub_path   = "garage.toml"
            read_only  = true
          }

          volume_mount {
            name       = "meta"
            mount_path = local.metadata_dir
          }

          volume_mount {
            name       = "data"
            mount_path = local.data_dir
          }

          resources {
            requests = {
              cpu    = var.cpu_request
              memory = var.memory_request
            }
            limits = {
              cpu    = var.cpu_limit
              memory = var.memory_limit
            }
          }

          # `/health` is the admin API's unauthenticated liveness/readiness
          # endpoint. It returns 503 whenever this node cannot answer API
          # requests — which, on a fresh install, includes "no cluster layout
          # has been committed yet". That makes it exactly right for READINESS:
          # the S3 Service gets no endpoints until Garage can actually serve.
          readiness_probe {
            http_get {
              path = "/health"
              port = "admin"
            }
            initial_delay_seconds = 5
            period_seconds        = 10
            timeout_seconds       = 3
            failure_threshold     = 3
          }

          # ...and exactly WRONG for liveness, which is why this is a TCP check
          # instead. A node awaiting its one-time layout bootstrap is healthy but
          # unready; an HTTP liveness probe on /health would restart-loop that
          # pod forever and the operator could never complete the bootstrap.
          liveness_probe {
            tcp_socket {
              port = "admin"
            }
            initial_delay_seconds = 15
            period_seconds        = 20
            failure_threshold     = 3
          }
        }

        volume {
          name = "config"
          config_map {
            name = kubernetes_config_map.garage.metadata[0].name
          }
        }
      }
    }

    # TWO separate claims, deliberately. Metadata is small, latency-sensitive
    # and access-heavy; object data is bulk. Keeping them apart means metadata
    # can move to a faster storage class later without resizing or migrating
    # the bulk volume. Both sizes come from module variables — the data size is
    # the hard ceiling on this dependency's contribution to node disk pressure.
    volume_claim_template {
      metadata {
        name = "meta"
      }
      spec {
        access_modes = ["ReadWriteOnce"]
        resources {
          requests = {
            storage = var.meta_pvc_size
          }
        }
      }
    }

    volume_claim_template {
      metadata {
        name = "data"
      }
      spec {
        access_modes = ["ReadWriteOnce"]
        resources {
          requests = {
            storage = var.data_pvc_size
          }
        }
      }
    }
  }

  # A fresh Garage node never becomes Ready: it holds no cluster layout, so
  # /health stays 503 until the operator runs the one-time bootstrap. Waiting
  # for the rollout here would block the apply on an opaque timeout. Instead the
  # apply proceeds to the provisioning Job, which polls for health and fails
  # with a message naming the bootstrap procedure. One clear error, one place.
  wait_for_rollout = false
}

# Headless governing Service. Also the in-cluster address of the ADMIN API
# (:3903) — which is never routed by an Ingress; see ingress.tf and design D6.
#
# publish_not_ready_addresses is load-bearing: on a fresh install the pod is
# deliberately not Ready until the cluster layout is committed, and the
# provisioning Job has to be able to reach the admin API before that to tell the
# operator so. A readiness-gated Service would have no endpoints and the Job
# would fail with a connection error instead of the actionable message.
resource "kubernetes_service" "garage" {
  metadata {
    name      = "garage"
    namespace = var.namespace
    labels    = local.labels
  }

  spec {
    cluster_ip                  = "None"
    publish_not_ready_addresses = true
    selector                    = local.labels

    port {
      name        = "s3"
      port        = 3900
      target_port = "s3"
      protocol    = "TCP"
    }

    port {
      name        = "admin"
      port        = 3903
      target_port = "admin"
      protocol    = "TCP"
    }
  }
}

# The S3 Service, and the only one an Ingress points at. ClusterIP and
# readiness-gated on purpose: while Garage cannot serve (no layout, or starting
# up), Traefik sees no endpoint and returns 503 rather than forwarding into a
# node that will reject everything. It exposes port 3900 ONLY — the admin port
# is deliberately absent, so no Ingress can reach it even by mistake.
resource "kubernetes_service" "garage_s3" {
  metadata {
    name      = "garage-s3"
    namespace = var.namespace
    labels    = local.labels
  }

  spec {
    type     = "ClusterIP"
    selector = local.labels

    port {
      name        = "s3"
      port        = 3900
      target_port = "s3"
      protocol    = "TCP"
    }
  }
}
