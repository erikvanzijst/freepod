variable "namespace" {
  type = string
}

variable "bucket" {
  type = string
}

variable "s3_url" {
  type = string
}

variable "s3_access_key_id" {
  type      = string
  sensitive = true
}

variable "s3_secret_access_key" {
  type      = string
  sensitive = true
}

variable "repo_password" {
  type      = string
  sensitive = true
}

variable "sse_c_key" {
  type      = string
  sensitive = true
}
