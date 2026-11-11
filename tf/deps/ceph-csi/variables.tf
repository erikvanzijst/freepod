variable "namespace" {
  description = "Namespace for the CSI driver and the pools' credentials."
  type        = string
}

variable "cluster_id" {
  description = "The Ceph cluster's fsid (`ceph fsid`)."
  type        = string
}

variable "monitors" {
  description = "Ceph monitor addresses, `host:port`."
  type        = list(string)
}

variable "storage_classes" {
  description = "StorageClass name => the RBD pool it provisions into, the Ceph client (without `client.`) scoped to that pool, and the reclaim policy."
  type = map(object({
    pool           = string
    user_id        = string
    reclaim_policy = string
  }))
}

variable "user_keys" {
  description = "Ceph client name (without `client.`) => its cephx key (`ceph auth print-key client.<name>`)."
  type        = map(string)
  sensitive   = true
}
