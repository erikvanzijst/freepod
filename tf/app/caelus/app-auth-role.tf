# The app authentication service's database credential and the bootstrap that
# creates it. Same shape as ssh-resolver-role.tf: app-auth itself runs in the
# login namespace (tf/app/app-auth); only its role belongs with the database.
resource "random_password" "app_auth_db" {
  length  = 32
  special = false
}

resource "kubernetes_secret" "app_auth_db_bootstrap" {
  metadata {
    name      = "caelus-app-auth-db"
    namespace = var.namespace
  }

  type = "Opaque"

  data = {
    APP_AUTH_PASSWORD = random_password.app_auth_db.result
  }
}

resource "kubernetes_config_map" "app_auth_bootstrap" {
  metadata {
    name      = "caelus-app-auth-bootstrap"
    namespace = var.namespace
  }

  data = {
    "app-auth-bootstrap.sql" = file("${path.module}/app-auth-bootstrap.sql")
  }
}
