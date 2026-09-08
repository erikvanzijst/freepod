module "oauth2-proxy" {
  source    = "./login"
  namespace = kubernetes_namespace.login.metadata[0].name
  domain    = local.domain

  # Select this workspace's Keycloak client. The clients themselves are
  # declared in tf/deps (the singleton root module); tf/app only chooses.
  oauth2_proxy_client_id     = var.oauth2_proxy_client_ids[terraform.workspace]
  oauth2_proxy_client_secret = var.oauth2_proxy_client_secrets[terraform.workspace]
  oauth2_proxy_cookie_secret = var.oauth2_proxy_cookie_secret

  # Dev is gated on Keycloak group membership; prod is open to anyone who has
  # registered. Registration is realm-level and the realm is shared, so this is
  # the only place the two environments can diverge on who gets in.
  allowed_groups = local.is_prod_workspace ? [] : ["freepod-dev"]
}

# The public half of this environment's upstream key. Derived here rather than
# inside the sshpiper module because both modules need it and that module
# already depends on module.caelus for the resolver's database URL -- deriving
# it there and passing it back would be a cycle.
data "tls_public_key" "sshpiper_upstream" {
  private_key_openssh = var.sshpiper_upstream_private_keys[terraform.workspace]
}

# The public half of this environment's edge host key -- the key the edge
# presents to clients, which the API publishes at GET /api/ssh
data "tls_public_key" "sshpiper_host" {
  private_key_openssh = var.sshpiper_host_private_keys[terraform.workspace]
}

module "sshpiper" {
  source    = "./sshpiper"
  namespace = kubernetes_namespace.sshpiper.metadata[0].name
  ssh_port  = local.sshpiper_port
  rbac_name = "sshpiper-${local.ns_sshpiper}"

  # This environment's private keys for both upstream and downstream:
  sshpiper_host_private_key = var.sshpiper_host_private_keys[terraform.workspace]
  upstream_private_key      = var.sshpiper_upstream_private_keys[terraform.workspace]

  resolver_image = var.ssh_resolver_image

  resolver_database_url = format(
    "postgresql://%s:%s@%s:5432/%s",
    module.caelus.ssh_resolver_db_role,
    module.caelus.ssh_resolver_db_password,
    module.caelus.database_host,
    module.caelus.database_name,
  )
}

module "caelus" {
  source             = "./caelus"
  namespace          = kubernetes_namespace.caelus.metadata[0].name
  environment        = local.environment
  domain             = local.domain
  api_image          = local.api_image
  ui_image           = local.ui_image
  rbac_name          = "caelus-api-${kubernetes_namespace.caelus.metadata[0].name}"
  ns_login           = kubernetes_namespace.login.metadata[0].name
  db_password        = var.db_password
  wildcard_domains   = [local.domain]
  reserved_hostnames = var.reserved_hostnames[terraform.workspace]
  mollie_api_key     = var.mollie_api_key
  sshpiper_namespace = kubernetes_namespace.sshpiper.metadata[0].name
  builds_namespace   = kubernetes_namespace.builds.metadata[0].name
  builder_image      = var.builder_image
  sftp_host          = local.sftp_host
  sftp_port          = local.sftp_port

  # Every sidecar trusts this; the edge holds the private half. The reconciler
  # injects it into each chart as caelus.sftp.platformPublicKey.
  sftp_platform_public_key = trimspace(data.tls_public_key.sshpiper_upstream.public_key_openssh)
  ssh_edge_host_public_key = trimspace(data.tls_public_key.sshpiper_host.public_key_openssh)

  # Select this workspace's Garage bucket and key. Like the Keycloak clients
  # above, the buckets and keys themselves are created in tf/deps (the singleton
  # root module); tf/app only chooses which pair this environment gets.
  s3_endpoint_url      = var.s3_endpoint_url
  s3_region            = var.s3_region
  s3_bucket            = var.s3_buckets[terraform.workspace]
  s3_access_key_id     = var.s3_access_key_ids[terraform.workspace]
  s3_secret_access_key = var.s3_secret_access_keys[terraform.workspace]

  garage_admin_url   = var.garage_admin_url
  garage_admin_token = var.garage_admin_token

  # Per workspace, like the Garage key above and for the same reason: a dev key
  # must not decrypt a prod tenant's secrets. Defaults to empty so a workspace
  # that has not been given one still plans -- legal only while no product
  # template declares vars.
  var_encryption_keys = lookup(var.var_encryption_keys, terraform.workspace, [])

  # Loki, like Garage above, is a tf/deps singleton shared by both workspaces.
  loki_base_url         = var.loki_base_url
  log_keepalive_seconds = var.log_keepalive_seconds

  depends_on = [kubernetes_namespace.caelus, kubernetes_namespace.builds]
}
