resource "kubernetes_namespace" "keycloak" {
  metadata {
    name = "keycloak"
  }
}

resource "kubernetes_namespace" "echo" {
  metadata {
    name = "echo"
  }
}

resource "kubernetes_namespace" "mailer" {
  metadata {
    name = "mailer"
  }
}

resource "kubernetes_namespace" "monitoring" {
  metadata {
    name = "monitoring"
  }
}

resource "kubernetes_namespace" "garage" {
  metadata {
    name = "garage"
  }
}

module "keycloak" {
  source                  = "./keycloak"
  namespace               = kubernetes_namespace.keycloak.metadata[0].name
  keycloak_admin_password = var.keycloak_admin_password
  keycloak_image          = var.keycloak_image
  domain                  = "freepod.eu"
}

# Realm, client, client-scope and group configuration for the Keycloak instance
# deployed by module.keycloak above. Kept as a separate module because it talks
# to Keycloak's admin API rather than to Kubernetes, and because it must not be
# applied until Keycloak is actually serving.
#
# Realm email is deliberately NOT wired from var.smtp_* here. Those are the
# mailer relay's own upstream purelymail credentials (see module.mailer below);
# the realm sends through the relay instead and defaults to it.
module "keycloak_config" {
  source = "./keycloak-config"

  depends_on = [module.keycloak, module.mailer]
}

module "certmanager" {
  source               = "./certmanager"
  cloudflare_api_token = var.cloudflare_api_token
  letsencrypt_email    = var.letsencrypt_email
}

# Cluster singleton shared by dev and prod: Traefik honours one TLSStore named
# `default`, and only in the namespace module.system pins it to.
module "tls" {
  source = "./tls"

  depends_on = [module.system]
}

module "system" {
  source                          = "./system"
  haproxy_edge_ip                 = var.haproxy_edge_ip
  default_tls_resources_namespace = "caelus-tls"

  # Traefik's default cert store points at the wildcard secret cert-manager issues.
  depends_on = [module.certmanager]
}

# One instance serves BOTH environments (tf/deps is workspace-less); separation
# is by bucket and access-key naming, like the freepod-dev / freepod-prod split
# in Keycloak.
module "garage" {
  source    = "./garage"
  namespace = kubernetes_namespace.garage.metadata[0].name
  domain    = "freepod.eu"

  admin_token = var.garage_admin_token
  rpc_secret  = var.garage_rpc_secret
}

module "mailer" {
  source        = "./mailer"
  namespace     = kubernetes_namespace.mailer.metadata[0].name
  smtp_host     = var.smtp_host
  smtp_port     = var.smtp_port
  smtp_username = var.smtp_username
  smtp_password = var.smtp_password
}

# --- Monitoring stack (cluster-wide observability) ---

module "loki" {
  source    = "./loki"
  namespace = kubernetes_namespace.monitoring.metadata[0].name
}

module "prometheus" {
  source                 = "./prometheus"
  namespace              = kubernetes_namespace.monitoring.metadata[0].name
  grafana_admin_password = var.grafana_admin_password
  alert_email_to         = var.alert_email_to
  # Sourced from the Terraform-managed `grafana` client in the freepod realm,
  # not from a hand-maintained tfvar: the client is declared in
  # ./keycloak-config, so its ID and generated secret are already known here.
  # This removes the last manual Keycloak secret from tf/deps.
  grafana_oidc_client_id     = module.keycloak_config.grafana_client_id
  grafana_oidc_client_secret = module.keycloak_config.grafana_client_secret

  # Alertmanager delivers via the in-cluster mailer relay.
  depends_on = [module.mailer]
}
