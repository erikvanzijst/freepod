variable "namespace" {
  description = "Namespace the heartbeat CronJobs run in."
  type        = string
}

variable "probes" {
  description = "Probes keyed by check name. Each run requests `url` through the public edge (2xx/3xx is up) and reports the outcome to that check's ping URL. `node_pool` pins the probe to the nodes labeled and tainted caelus.dev/node-pool=<pool>, so the check also fails when that pool cannot run it."
  type = map(object({
    url       = string
    node_pool = optional(string)
  }))
}

variable "ping_urls" {
  description = "healthchecks.io ping URL, keyed by check name; every key of `probes` needs one."
  type        = map(string)
  sensitive   = true
}

variable "schedule" {
  description = "Cron schedule of every probe."
  type        = string
  default     = "* * * * *"
}

variable "image" {
  description = "curl image the probes run."
  type        = string
  default     = "curlimages/curl:8.23.0"
}
