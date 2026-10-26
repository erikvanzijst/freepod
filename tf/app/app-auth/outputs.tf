output "oidc_issuer" {
  description = "The OpenID Provider's issuer, which SSO-enabled charts are configured with."
  value       = "https://login.${var.domain}"
}

output "oidc_client_keys" {
  description = "The keyring OIDC client secrets are derived from; the reconciler derives with it too."
  value       = local.oidc_client_keys
  sensitive   = true
}
