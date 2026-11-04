variable "node_pool" {
  description = "Node pool whose nodes have the gVisor runtime installed, by the caelus.dev/node-pool label and taint."
  type        = string
}
