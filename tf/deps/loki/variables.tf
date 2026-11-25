variable "namespace" {
  description = "Namespace to deploy into"
  type        = string
}

variable "storage_class" {
  description = "StorageClass of Loki's volume"
  type        = string
}
