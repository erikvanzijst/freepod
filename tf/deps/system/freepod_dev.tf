# freepod.dev is a vanity domain that, for now, only redirects to the developer
# landing page. Its DNS is on deSEC rather than Cloudflare, so the DNS-01 issuer
# behind the platform wildcard cannot cover it; HTTP-01 works because :80 already
# reaches this Traefik (the solver out-ranks redirect_https.tf's catch-all).
resource "kubernetes_manifest" "freepod_dev_certificate" {
  manifest = {
    apiVersion = "cert-manager.io/v1"
    kind       = "Certificate"
    metadata = {
      name      = "freepod-dev"
      namespace = "kube-system"
    }
    spec = {
      secretName = "freepod-dev-tls"
      issuerRef = {
        name = "letsencrypt-http"
        kind = "ClusterIssuer"
      }
      dnsNames = ["freepod.dev"]
    }
  }
}

resource "kubernetes_manifest" "freepod_dev_redirect_middleware" {
  manifest = {
    apiVersion = "traefik.io/v1alpha1"
    kind       = "Middleware"
    metadata = {
      name      = "redirect-freepod-dev"
      namespace = "kube-system"
    }
    spec = {
      redirectRegex = {
        regex       = "^.*$"
        replacement = "https://freepod.eu/dev"
        # Temporary (302) so browsers don't cache it once freepod.dev gets content.
        permanent = false
      }
    }
  }

  depends_on = [module.traefik]
}

resource "kubernetes_manifest" "freepod_dev_route" {
  manifest = {
    apiVersion = "traefik.io/v1alpha1"
    kind       = "IngressRoute"
    metadata = {
      name      = "freepod-dev"
      namespace = "kube-system"
    }
    spec = {
      entryPoints = ["websecure"]
      routes = [{
        match = "Host(`freepod.dev`)"
        kind  = "Rule"
        middlewares = [{
          name = kubernetes_manifest.freepod_dev_redirect_middleware.manifest.metadata.name
        }]
        # Never hit: the redirect short-circuits first (see redirect_https.tf).
        services = [{
          name = "traefik"
          port = 80
        }]
      }]
      tls = {
        secretName = kubernetes_manifest.freepod_dev_certificate.manifest.spec.secretName
      }
    }
  }
}
