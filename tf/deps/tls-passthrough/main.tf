# TLS passthrough by SNI to other hosts on the LAN, on Traefik's websecure entry point.
# Traefik matches TLS TCP routers before HTTPS routers, so these names never reach
# freepod's own routers. Port 80 needs nothing here: freepod's catch-all redirects any
# host to HTTPS.

locals {
  rules = {
    for name, r in var.routes : name => join(" && ", compact([
      "(${join(" || ", [for d in r.domains : "HostSNIRegexp(`^(.+\\.)?${replace(d, ".", "\\.")}$`)"])})",
      length(r.except) > 0 ? "!(${join(" || ", [for h in r.except : "HostSNI(`${h}`)"])})" : "",
    ]))
  }
}

resource "kubernetes_service" "target" {
  for_each = var.routes

  metadata {
    name      = "passthrough-${each.key}"
    namespace = var.namespace
  }

  spec {
    port {
      name        = "tls"
      protocol    = "TCP"
      port        = each.value.port
      target_port = each.value.port
    }
  }
}

resource "kubernetes_endpoint_slice_v1" "target" {
  for_each = var.routes

  metadata {
    name      = "passthrough-${each.key}"
    namespace = var.namespace
    labels = {
      "kubernetes.io/service-name"             = kubernetes_service.target[each.key].metadata[0].name
      "endpointslice.kubernetes.io/managed-by" = "terraform"
    }
  }

  address_type = "IPv4"

  endpoint {
    addresses = [each.value.address]
    condition {
      ready = true
    }
  }

  port {
    name         = "tls"
    protocol     = "TCP"
    port         = each.value.port
    app_protocol = "tcp"
  }
}

resource "kubernetes_manifest" "proxy_protocol" {
  for_each = var.routes

  manifest = {
    apiVersion = "traefik.io/v1alpha1"
    kind       = "ServersTransportTCP"
    metadata = {
      name      = "passthrough-${each.key}"
      namespace = var.namespace
    }
    spec = {
      proxyProtocol = {
        version = 2
      }
    }
  }
}

resource "kubernetes_manifest" "route" {
  for_each = var.routes

  manifest = {
    apiVersion = "traefik.io/v1alpha1"
    kind       = "IngressRouteTCP"
    metadata = {
      name      = "passthrough-${each.key}"
      namespace = var.namespace
    }
    spec = {
      entryPoints = ["websecure"]
      routes = [{
        match = local.rules[each.key]
        services = [{
          name             = kubernetes_service.target[each.key].metadata[0].name
          port             = each.value.port
          serversTransport = kubernetes_manifest.proxy_protocol[each.key].manifest.metadata.name
        }]
      }]
      tls = {
        passthrough = true
      }
    }
  }
}
