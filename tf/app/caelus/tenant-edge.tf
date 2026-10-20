# What the edge serves on the tenant domain's own names: the apex points
# visitors back to the platform, and each retired `<app>.<handle>.<domain>`
# hostname permanently redirects to `<app>-<handle>.<tenant_domain>`. Both are
# served by the store's certificates: the apex by the default one, the retired
# names by the per-account certificates still listed in the store.

resource "kubernetes_manifest" "tenant_apex_redirect" {
  manifest = {
    apiVersion = "traefik.io/v1alpha1"
    kind       = "Middleware"
    metadata = {
      name      = "redirect-tenant-apex"
      namespace = var.namespace
    }
    spec = {
      redirectRegex = {
        regex       = "^.*$"
        replacement = "https://${var.domain}"
        permanent   = true
      }
    }
  }
}

resource "kubernetes_manifest" "tenant_apex_route" {
  manifest = {
    apiVersion = "traefik.io/v1alpha1"
    kind       = "IngressRoute"
    metadata = {
      name      = "tenant-apex"
      namespace = var.namespace
    }
    spec = {
      entryPoints = ["websecure"]
      routes = [{
        match = "Host(`${var.tenant_domain}`)"
        kind  = "Rule"
        middlewares = [{
          name = kubernetes_manifest.tenant_apex_redirect.manifest.metadata.name
        }]
        # Never reached: the redirect answers first.
        services = [{
          name = kubernetes_service.api.metadata[0].name
          port = 8000
        }]
      }]
      tls = {}
    }
  }
}

locals {
  legacy_tenant_redirect_count = nonsensitive(length(var.legacy_tenant_redirects)) > 0 ? 1 : 0
}

# A permanent redirectRegex answers GET with 301 and every other method with
# 308, so a method and its body survive the move. Explicit Host rules rather
# than a host regex: a pattern over `*.*.<domain>` would also capture platform
# hosts such as `cr.dev.freepod.eu`.
resource "kubernetes_manifest" "legacy_tenant_redirect" {
  count = local.legacy_tenant_redirect_count

  manifest = {
    apiVersion = "traefik.io/v1alpha1"
    kind       = "Middleware"
    metadata = {
      name      = "redirect-legacy-tenant"
      namespace = var.namespace
    }
    spec = {
      redirectRegex = {
        regex       = "^https://([^.]+)\\.([^.]+)\\.${replace(var.domain, ".", "\\.")}(.*)"
        replacement = "https://$${1}-$${2}.${var.tenant_domain}$${3}"
        permanent   = true
      }
    }
  }
}

resource "kubernetes_manifest" "legacy_tenant_route" {
  count = local.legacy_tenant_redirect_count

  manifest = {
    apiVersion = "traefik.io/v1alpha1"
    kind       = "IngressRoute"
    metadata = {
      name      = "legacy-tenant-hostnames"
      namespace = var.namespace
    }
    spec = {
      entryPoints = ["websecure"]
      routes = [{
        match = join(" || ", [for host in var.legacy_tenant_redirects : "Host(`${host}`)"])
        kind  = "Rule"
        middlewares = [{
          name = kubernetes_manifest.legacy_tenant_redirect[0].manifest.metadata.name
        }]
        # Never reached: the redirect answers first.
        services = [{
          name = kubernetes_service.api.metadata[0].name
          port = 8000
        }]
      }]
      tls = {}
    }
  }
}
