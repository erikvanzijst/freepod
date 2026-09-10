resource "kubernetes_config_map" "api" {
  metadata {
    name      = "caelus-api-config"
    namespace = var.namespace
  }

  data = {
    CAELUS_BASE_URL                 = "https://${var.domain}"
    CAELUS_BASE_URL_API             = "https://${var.domain}/api/"
    CAELUS_STATIC_PATH              = "/var/static"
    CAELUS_DATABASE_URL             = "postgresql+psycopg://${var.db_user}:${var.db_password}@caelus-postgres:5432/${var.db_name}"
    CAELUS_ENVIRONMENT              = var.environment
    CAELUS_DOMAIN                   = var.domain
    CAELUS_WILDCARD_DOMAINS         = jsonencode(var.wildcard_domains)
    CAELUS_RESERVED_HOSTNAMES       = jsonencode(var.reserved_hostnames)
    CAELUS_MOLLIE_API_KEY           = var.mollie_api_key
    CAELUS_MOLLIE_REDIRECT_URL      = "https://${var.domain}"
    CAELUS_MOLLIE_WEBHOOK_BASE_URL  = "https://${var.domain}/api/"
    CAELUS_SSHPIPER_NAMESPACE       = var.sshpiper_namespace
    CAELUS_SFTP_PLATFORM_PUBLIC_KEY = var.sftp_platform_public_key
    CAELUS_SSH_EDGE_HOST_PUBLIC_KEY = var.ssh_edge_host_public_key
    CAELUS_SFTP_HOST                = var.sftp_host
    CAELUS_SFTP_PORT                = tostring(var.sftp_port)

    # The tenant database pooler. Addresses, not credentials -- the admin
    # credential rides in the caelus-tenant-db Secret, on the worker only.
    # These are here because two different things need them and neither is a
    # secret: the published DATABASE_URL points a tenant pod at the pooler, and
    # the tenant NetworkPolicy scopes its one database egress rule to that
    # namespace, pod label and port.
    CAELUS_TENANT_DB_POOLER_HOST      = "${kubernetes_service.tenant_pooler.metadata[0].name}.${var.namespace}.svc.cluster.local"
    CAELUS_TENANT_DB_POOLER_PORT      = "6432"
    CAELUS_TENANT_DB_POOLER_NAMESPACE = var.namespace
    CAELUS_TENANT_DB_POOLER_POD_LABEL = local.tenant_pooler_app_label

    # The quota ladder's threshold mails. The relay is a tf/deps singleton that
    # accepts unauthenticated mail from in-cluster namespaces, so there is no
    # credential to carry.
    CAELUS_SMTP_HOST = "smtp.${var.mailer_namespace}.svc.cluster.local"
    CAELUS_SMTP_PORT = "25"
    CAELUS_SMTP_FROM = "no-reply@${var.domain}"

    CAELUS_ARTIFACT_MAX_BYTES  = 200 * 1024 * 1024
    CAELUS_BUILDER_IMAGE       = var.builder_image
    CAELUS_BUILDS_NAMESPACE    = var.builds_namespace
    CAELUS_BUILD_MAX_IN_FLIGHT = tostring(var.build_max_in_flight)

    # Deployment logs. Loki is a singleton in tf/deps, shared by both
    # workspaces, and is reached in-cluster -- it is deliberately not routed by
    # an Ingress, so a tenant cannot query it directly. It has
    # `auth_enabled = false` and holds every tenant's output *and* the
    # platform's own in one tenancy, which is why the API builds every selector
    # itself and accepts none from a client.
    #
    # Without this the API answers every log request with "log store is not
    # configured" -- the setting defaults to empty so that migrations, tests
    # and the operator CLI still construct settings without it.
    CAELUS_LOKI_BASE_URL = var.loki_base_url
    # Below the shortest connection timeout in the path, which is not a
    # property of this repository: client -> homelab HAProxy -> Traefik -> API,
    # and HAProxy's timeouts are operator-configured. Re-measure against the
    # live edge before raising it.
    CAELUS_LOG_KEEPALIVE_SECONDS = tostring(var.log_keepalive_seconds)

    # CAELUS_LOG_LEVEL    = "info"
    PYTHONUNBUFFERED = "1"

    # Trust X-Forwarded-For/Proto from the in-cluster Traefik pod so uvicorn
    # reports the real client IP instead of the proxy's pod IP. Value is the
    # k3s pod CIDR; uvicorn walks the XFF chain in reverse and returns the
    # first host outside this range.
    FORWARDED_ALLOW_IPS = "10.42.0.0/16"
  }
}
