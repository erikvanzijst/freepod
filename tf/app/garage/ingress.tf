# We do not apply any auth middlewares to Garage, as it implements its own
# authn/authz and has no use for X-Auth-Email headers.
#
# Garage authenticates with AWS SigV4 — either an `Authorization` header or
# a presigned URL whose signature lives in the query string. There is no
# session cookie, so oauth2-proxy returns 401 before Garage is ever reached.
#
# There is also no `buffering` middleware and no `maxRequestBodyBytes`, here or
# anywhere else in the Traefik path. Large uploads must stream straight through:
# buffering would defeat the whole point of a presigned URL, which is that bytes
# flow from the client to storage without being staged in between.
resource "kubernetes_ingress_v1" "garage_s3" {
  metadata {
    name      = "garage-s3"
    namespace = var.namespace

    annotations = {
      "kubernetes.io/ingress.class" = "traefik"
    }
  }

  spec {
    rule {
      host = var.host

      http {
        path {
          path      = "/"
          path_type = "Prefix"

          backend {
            service {
              # garage-s3 exposes port 3900 only. The admin API (:3903) is not
              # on this Service at all, so it cannot be routed from outside the
              # cluster even by an annotation mistake. Design D6.
              name = kubernetes_service.garage_s3.metadata[0].name
              port {
                number = 3900
              }
            }
          }
        }
      }
    }
  }
}

moved {
  from = kubernetes_ingress_v1.garage_s3[0]
  to   = kubernetes_ingress_v1.garage_s3
}
