# Sign in with Google, offered on the realm's login page to every client.
#
# The OAuth web client lives in the Google Cloud console (project `freepod`,
# Google Auth Platform > Clients), not in Terraform. Its registered redirect URI
# is derived from the alias below:
#   https://keycloak.freepod.eu/realms/freepod/broker/google/endpoint
# so renaming the alias breaks sign-in until the Google client is updated.
resource "keycloak_oidc_google_identity_provider" "google" {
  realm         = keycloak_realm.freepod.id
  alias         = "google"
  display_name  = "Google"
  enabled       = true
  client_id     = var.google_client_id
  client_secret = var.google_client_secret

  default_scopes = "openid profile email"

  # A first Google sign-in creates an account whose email is already verified.
  trust_email = true

  # Copy name and email once, at account creation. FORCE would rewrite the
  # Keycloak email whenever the Google address changes, and since the API
  # resolves callers by email, that silently moves the person to a new, empty
  # Freepod account. Stays IMPORT until openspec change keycloak-subject-join-key
  # makes the subject the join key.
  sync_mode = "IMPORT"

  # The stock flow: an email that already has an account must be confirmed and
  # proven (emailed link or password) before the Google identity is linked.
  # Never swap in an auto-link flow; see openspec google-sign-in design.md D2.
  first_broker_login_flow_alias = "first broker login"

  store_token                   = false
  add_read_token_role_on_create = false
  request_refresh_token         = false
}
