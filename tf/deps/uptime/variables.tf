variable "namespace" {
  description = "Namespace the heartbeat CronJobs run in."
  type        = string
}

variable "probes" {
  description = "Public URL to probe, keyed by check name. Each run requests the URL through the public edge (2xx/3xx is up) and reports the outcome to that check's ping URL."
  type        = map(string)
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
