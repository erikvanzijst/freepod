# The `gvisor` RuntimeClass: pods that name it run inside a gVisor sandbox.
# Only the node pool's nodes have the runtime installed (see ../README.md), so
# the class pins its pods there; they wait rather than land on a node without it.
resource "kubernetes_manifest" "gvisor" {
  manifest = {
    apiVersion = "node.k8s.io/v1"
    kind       = "RuntimeClass"
    metadata = {
      name = "gvisor"
    }
    handler = "runsc"
    # The sandbox's own memory, about 75 MiB per pod across real tenant apps,
    # is charged to the pod's cgroup. Declaring it keeps scheduling honest and
    # raises the pod-level limit so it doesn't come out of the app's limit.
    overhead = {
      podFixed = {
        memory = "80Mi"
        cpu    = "10m"
      }
    }
    scheduling = {
      nodeSelector = {
        "caelus.dev/node-pool" = var.node_pool
      }
      tolerations = [
        {
          key      = "caelus.dev/node-pool"
          operator = "Equal"
          value    = var.node_pool
          effect   = "NoSchedule"
        }
      ]
    }
  }
}
