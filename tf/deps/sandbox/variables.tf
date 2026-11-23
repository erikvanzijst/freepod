variable "node_pool" {
  description = "Node pool whose caelus.dev/node-pool taint sandboxed pods tolerate."
  type        = string
}
