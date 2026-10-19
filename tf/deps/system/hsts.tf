# Cluster-wide HSTS header for freepod (see openspec/changes/global-hsts-headers/).
# A traefik.io/v1alpha1 Middleware named `headers-hsts` in kube-system that sets
# `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload` on every
# HTTPS app response. Attached as a default middleware on the `websecure` entrypoint
# ONLY (not `web`), so ACME HTTP-01 and the HTTP->HTTPS redirect on :80 are unaffected.
resource "kubernetes_manifest" "headers_hsts_middleware" {
  manifest = {
    apiVersion = "traefik.io/v1alpha1"
    kind       = "Middleware"
    metadata = {
      name      = "headers-hsts"
      namespace = "kube-system"
    }
    spec = {
      headers = {
        stsSeconds           = 31536000
        stsIncludeSubdomains = true
        stsPreload           = true
        forceSTSHeader       = true
        # Clear-Site-Data "cookies" applies beyond the host that sends it, and
        # no platform route sends it.
        customResponseHeaders = {
          "Clear-Site-Data" = ""
        }
      }
    }
  }

  # The traefik.io/v1alpha1 CRDs are installed by the Traefik Helm release.
  # NOTE: this object is created AFTER Traefik, but the Helm values reference it
  # as a `websecure` default middleware. Until it exists, Traefik cannot resolve
  # that default and returns 500 for all :443 traffic — a transient first-apply /
  # restart window that self-heals once this applies. See design.md Risks.
  depends_on = [module.traefik]
}
