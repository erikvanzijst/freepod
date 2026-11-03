# The realm's browser flow: a copy of Keycloak's built-in `browser` flow with one
# step added, so that a passkey sign-in skips OTP. A passkey already proves
# possession and user verification. Built-in flows cannot be edited, hence the
# copy; new 26 realms have this condition in their own built-in flow.
#
# copy_from snapshots the built-in flow: Terraform tracks only the resources
# below, not the copied steps, and Keycloak upgrades do not update the copy.
resource "keycloak_authentication_flow" "browser" {
  realm_id    = keycloak_realm.freepod.id
  alias       = "freepod browser"
  description = "Keycloak's browser flow, skipping OTP after a passkey sign-in"
  copy_from   = "browser"
}

# The copied subflows are named "<flow alias> <original alias>".
resource "keycloak_authentication_execution" "skip_otp_after_passkey" {
  realm_id          = keycloak_realm.freepod.id
  parent_flow_alias = "${keycloak_authentication_flow.browser.alias} Browser - Conditional OTP"
  authenticator     = "conditional-credential"
  requirement       = "REQUIRED"
  priority          = 15
}

# Holds when the sign-in did not use a passkey.
resource "keycloak_authentication_execution_config" "skip_otp_after_passkey" {
  realm_id     = keycloak_realm.freepod.id
  execution_id = keycloak_authentication_execution.skip_otp_after_passkey.id
  alias        = "skip-otp-after-passkey"
  config = {
    credentials = "webauthn-passwordless"
  }
}

resource "keycloak_authentication_bindings" "freepod" {
  realm_id     = keycloak_realm.freepod.id
  browser_flow = keycloak_authentication_flow.browser.alias

  # Bind only once the copy is complete.
  depends_on = [keycloak_authentication_execution_config.skip_otp_after_passkey]
}
