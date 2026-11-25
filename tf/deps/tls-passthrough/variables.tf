variable "namespace" {
  type    = string
  default = "kube-system"
}

variable "routes" {
  description = "Hosts that receive the TLS connections whose SNI is one of their domains or a subdomain of one, untouched, with PROXY protocol v2: name => { address, port, domains, except }. `except` lists hostnames under those domains that stay with freepod."
  type = map(object({
    address = string
    port    = number
    domains = list(string)
    except  = optional(list(string), [])
  }))
}
