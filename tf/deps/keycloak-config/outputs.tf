output "realm_name" {
  description = "Name of the Freepod realm."
  value       = keycloak_realm.freepod.realm
}

output "freepod_prod_client_id" {
  description = "Client ID for the prod workspace of tf/app."
  value       = keycloak_openid_client.freepod_prod.client_id
}

output "freepod_prod_client_secret" {
  description = "Client secret for the prod workspace of tf/app. Copy into tf/app/secrets.auto.tfvars under the \"prod\" key."
  value       = keycloak_openid_client.freepod_prod.client_secret
  sensitive   = true
}

output "freepod_dev_client_id" {
  description = "Client ID for the default (dev) workspace of tf/app."
  value       = keycloak_openid_client.freepod_dev.client_id
}

output "freepod_dev_client_secret" {
  description = "Client secret for the default (dev) workspace of tf/app. Copy into tf/app/secrets.auto.tfvars under the \"default\" key — the dev workspace is named `default`, not `dev`."
  value       = keycloak_openid_client.freepod_dev.client_secret
  sensitive   = true
}

output "grafana_client_id" {
  description = "Client ID for Grafana, wired straight into module.prometheus."
  value       = keycloak_openid_client.grafana.client_id
}

output "grafana_client_secret" {
  description = "Client secret for Grafana, wired into module.prometheus so no manual secret is maintained."
  value       = keycloak_openid_client.grafana.client_secret
  sensitive   = true
}

output "freepod_apps_prod_client_id" {
  description = "App-authentication broker client ID for the prod workspace of tf/app."
  value       = keycloak_openid_client.freepod_apps_prod.client_id
}

output "freepod_apps_prod_client_secret" {
  description = "App-authentication broker client secret for the prod workspace of tf/app. Copy into tf/app/secrets.auto.tfvars under the \"prod\" key."
  value       = keycloak_openid_client.freepod_apps_prod.client_secret
  sensitive   = true
}

output "freepod_apps_dev_client_id" {
  description = "App-authentication broker client ID for the default (dev) workspace of tf/app."
  value       = keycloak_openid_client.freepod_apps_dev.client_id
}

output "freepod_apps_dev_client_secret" {
  description = "App-authentication broker client secret for the default (dev) workspace of tf/app. Copy into tf/app/secrets.auto.tfvars under the \"default\" key."
  value       = keycloak_openid_client.freepod_apps_dev.client_secret
  sensitive   = true
}
