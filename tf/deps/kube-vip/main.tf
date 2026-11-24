# One kube-vip per server that also serves ingress. The holder of the Lease carries the
# addresses and answers ARP/NDP for them; when it stops renewing, another takes over.

locals {
  labels = {
    "app.kubernetes.io/name" = "kube-vip"
  }
}

resource "kubernetes_service_account" "kube_vip" {
  metadata {
    name      = "kube-vip"
    namespace = var.namespace
  }
}

resource "kubernetes_cluster_role" "kube_vip" {
  metadata {
    name = "kube-vip"
  }

  rule {
    api_groups = [""]
    resources  = ["services/status"]
    verbs      = ["update"]
  }
  rule {
    api_groups = [""]
    resources  = ["services", "endpoints"]
    verbs      = ["list", "get", "watch", "update"]
  }
  rule {
    api_groups = [""]
    resources  = ["nodes"]
    verbs      = ["list", "get", "watch", "update", "patch"]
  }
  rule {
    api_groups = ["coordination.k8s.io"]
    resources  = ["leases"]
    verbs      = ["list", "get", "watch", "update", "create"]
  }
  rule {
    api_groups = ["discovery.k8s.io"]
    resources  = ["endpointslices"]
    verbs      = ["list", "get", "watch", "update"]
  }
  rule {
    api_groups = [""]
    resources  = ["pods"]
    verbs      = ["list"]
  }
}

resource "kubernetes_cluster_role_binding" "kube_vip" {
  metadata {
    name = "kube-vip"
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "ClusterRole"
    name      = kubernetes_cluster_role.kube_vip.metadata[0].name
  }

  subject {
    kind      = "ServiceAccount"
    name      = kubernetes_service_account.kube_vip.metadata[0].name
    namespace = var.namespace
  }
}

resource "kubernetes_daemonset" "kube_vip" {
  metadata {
    name      = "kube-vip"
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
      }

      spec {
        host_network         = true
        service_account_name = kubernetes_service_account.kube_vip.metadata[0].name
        priority_class_name  = "system-node-critical"
        enable_service_links = false

        node_selector = {
          "node-role.kubernetes.io/control-plane" = "true"
          "caelus.dev/edge"                       = "true"
        }

        toleration {
          operator = "Exists"
          effect   = "NoSchedule"
        }
        toleration {
          operator = "Exists"
          effect   = "NoExecute"
        }

        container {
          name  = "kube-vip"
          image = var.image
          # An empty prometheus_server env var is ignored, so the listener is switched off here.
          args = ["manager", "--prometheusHTTPServer="]

          env {
            name  = "address"
            value = join(",", var.addresses)
          }
          env {
            name  = "port"
            value = "6443"
          }
          env {
            name  = "vip_interface"
            value = var.interface
          }
          env {
            name  = "vip_subnet"
            value = "32,128"
          }
          env {
            name  = "vip_arp"
            value = "true"
          }
          env {
            name  = "cp_enable"
            value = "true"
          }
          env {
            name  = "cp_namespace"
            value = var.namespace
          }
          env {
            name  = "svc_enable"
            value = "false"
          }
          env {
            name  = "vip_leaderelection"
            value = "true"
          }
          env {
            name  = "vip_leasename"
            value = "plndr-cp-lock"
          }
          env {
            name = "vip_nodename"
            value_from {
              field_ref {
                field_path = "spec.nodeName"
              }
            }
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
            capabilities {
              drop = ["ALL"]
              add  = ["NET_ADMIN", "NET_RAW"]
            }
          }
        }
      }
    }
  }
}
