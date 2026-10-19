# The SPA reads no cookies, so none are forwarded to nginx.
resource "kubernetes_manifest" "strip_cookie" {
  manifest = {
    apiVersion = "traefik.io/v1alpha1"
    kind       = "Middleware"
    metadata = {
      name      = "strip-cookie"
      namespace = var.namespace
    }
    spec = {
      headers = {
        customRequestHeaders = {
          Cookie = ""
        }
      }
    }
  }
}

# Webhook endpoints bypass oauth2-proxy entirely — Mollie (and future
# providers) POST here without auth cookies, so no forward-auth middleware.
resource "kubernetes_ingress_v1" "webhooks" {
  metadata {
    name      = "caelus-webhooks-ingress"
    namespace = var.namespace

    annotations = {
      "traefik.ingress.kubernetes.io/router.entrypoints" = "websecure"
      "traefik.ingress.kubernetes.io/router.middlewares" = var.apex_headers_middleware
    }
  }

  spec {
    rule {
      host = var.domain

      http {
        path {
          path      = "/api/webhooks"
          path_type = "Prefix"

          backend {
            service {
              name = kubernetes_service.api.metadata[0].name
              port {
                number = 8000
              }
            }
          }
        }
      }
    }
  }
}

resource "kubernetes_ingress_v1" "caelus" {
  metadata {
    name      = "caelus-ingress"
    namespace = var.namespace

    annotations = {
      "traefik.ingress.kubernetes.io/router.entrypoints" = "websecure"
      # forward-auth injects the trusted X-Auth-Request-Email and returns 401
      # for anonymous requests. We intentionally do NOT attach oauth-errors
      # here anymore: anonymous API calls should surface as a clean 401 that
      # the SPA handles (by showing the public landing page), not an HTML
      # redirect to Keycloak. Login is initiated explicitly by the SPA via
      # /oauth2/start.
      "traefik.ingress.kubernetes.io/router.middlewares" = "${var.ns_login}-forward-auth@kubernetescrd,${var.apex_headers_middleware}"
    }
    # NOTE: this ingress covers only /api and /echo. The UI (/) is served
    # anonymously by the separate `caelus-ui-ingress` below so the public
    # landing page can load before login. /oauth2/* on this host is served
    # unauthenticated by the higher-priority `oauth2-endpoints` IngressRoute
    # (tf/app/login/main.tf). Genuinely-public API GET reads are allowed
    # through forward-auth by oauth2-proxy `skip_auth_routes` (also defined in
    # tf/app/login/main.tf).
  }

  spec {
    rule {
      host = var.domain

      http {
        path {
          path      = "/api"
          path_type = "Prefix"

          backend {
            service {
              name = kubernetes_service.api.metadata[0].name
              port {
                number = 8000
              }
            }
          }
        }

        path {
          path      = "/echo"
          path_type = "Prefix"

          backend {
            service {
              name = kubernetes_service.echo.metadata[0].name
              port {
                number = 8080
              }
            }
          }
        }
      }
    }
  }
}

# The UI (SPA) is served anonymously — no forward-auth middleware — so the
# public landing page can load before login. The bundle carries no secrets;
# the security boundary lives at the API (forward-auth + per-endpoint
# Depends). The SPA decides landing-vs-dashboard by calling GET /api/me.
#
# This is a lower-priority `/` router than the `/api` and `/echo` prefixes on
# caelus-ingress and the `/oauth2` IngressRoute, so those more-specific paths
# still win; everything else (the SPA and its assets) falls through to here.
resource "kubernetes_ingress_v1" "caelus_ui" {
  metadata {
    name      = "caelus-ui-ingress"
    namespace = var.namespace

    annotations = {
      "traefik.ingress.kubernetes.io/router.entrypoints" = "websecure"
      "traefik.ingress.kubernetes.io/router.middlewares" = "${var.apex_headers_middleware},${var.namespace}-${kubernetes_manifest.strip_cookie.manifest.metadata.name}@kubernetescrd"
    }
  }

  spec {
    rule {
      host = var.domain

      http {
        path {
          path      = "/"
          path_type = "Prefix"

          backend {
            service {
              name = kubernetes_service.ui.metadata[0].name
              port {
                number = 80
              }
            }
          }
        }
      }
    }
  }
}

resource "kubernetes_service" "echo_proxy" {
  metadata {
    name      = "echo-proxy"
    namespace = var.namespace
  }

  spec {
    # No selector — routes to the echo service in the echo namespace
    # via the manually-defined Endpoints resource below.
    port {
      port        = 8080
      target_port = 8080
    }
  }
}

data "kubernetes_service" "echo" {
  metadata {
    name      = "echo"
    namespace = "echo"
  }
}
