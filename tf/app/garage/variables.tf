variable "namespace" {
  description = "Namespace to deploy into"
  type        = string
}

variable "host" {
  description = "Public hostname of the S3 endpoint, e.g. blob.freepod.eu."
  type        = string
}

variable "garage_image" {
  description = "Garage container image, pinned to an explicit version."
  type        = string
  default     = "dxflrs/garage:v2.3.0"
}

variable "kubectl_image" {
  description = "Image for the provisioning Job. Must provide curl, jq and kubectl."
  type        = string
  default     = "alpine/k8s:1.31.1"
}

variable "meta_pvc_size" {
  description = "Size of the Garage metadata PVC (LMDB). Small, but must not be starved."
  type        = string
  default     = "2Gi"
}

variable "data_pvc_size" {
  description = "Size of the Garage object-data PVC. This is the hard ceiling on this dependency's contribution to node disk pressure."
  type        = string
  default     = "20Gi"
}

variable "cpu_request" {
  description = "CPU request. Idle Garage is cheap; do not over-reserve on a full node."
  type        = string
  default     = "100m"
}

variable "cpu_limit" {
  description = "CPU limit."
  type        = string
  default     = "1"
}

variable "memory_request" {
  description = "Memory request."
  type        = string
  default     = "256Mi"
}

variable "memory_limit" {
  description = "Memory limit. Caps a multipart-upload burst."
  type        = string
  default     = "1Gi"
}

# --- Provisioning ----------------------------------------------------------

variable "object_expiry_days" {
  description = "Age in days after which objects (and abandoned multipart uploads) are expired by the bucket lifecycle rules. Objects here are write-once/read-once and worthless within ~24h; 2 days leaves slack."
  type        = number
  default     = 2
}
