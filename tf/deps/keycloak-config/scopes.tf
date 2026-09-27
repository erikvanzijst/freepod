# The `groups` client scope.
#
# NOT a Keycloak built-in. Keycloak 24.0.5 ships ten default client scopes
# (acr, address, email, microprofile-jwt, offline_access, phone, profile,
# role_list, roles, web-origins); `groups` is absent from all of them. The one
# in the `master` realm was created by hand when Grafana was set up, which is
# exactly why it is on the `grafana` client and missing from `caelus-dev` — and
# therefore why group-based gating is not available to Freepod today. A fresh
# realm has nothing to attach, so the scope and its mapper are declared here.
resource "keycloak_openid_client_scope" "groups" {
  realm_id    = keycloak_realm.freepod.id
  name        = "groups"
  description = "Group membership, consumed by oauth2-proxy allowed_groups and Grafana"

  # Not an OAuth2 scope value clients request by name — it rides along as a
  # default scope, so keep it out of the `scope` claim. Mirrors `master`.
  include_in_token_scope = false
}

resource "keycloak_openid_group_membership_protocol_mapper" "groups" {
  realm_id        = keycloak_realm.freepod.id
  client_scope_id = keycloak_openid_client_scope.groups.id
  name            = "groups"
  claim_name      = "groups"

  # Emits bare names (`freepod-dev`) rather than paths (`/freepod-dev`).
  # oauth2-proxy's allowed_groups and Grafana's groups_attribute_path both
  # compare against bare names, so flipping this to true fails every login
  # closed. Verified as false on `master` today.
  full_path = false

  add_to_id_token     = true
  add_to_access_token = true
  add_to_userinfo     = true

  # No add_to_token_introspection: the argument does not exist before provider
  # 5.8.0, and we are capped below that for Keycloak 24 compatibility (see
  # ../providers.tf). The resulting mapper leaves `introspection.token.claim`
  # unset, where `master` has it explicitly "true" — the one deliberate
  # difference from the mapper being replaced. It is inert here: nothing reads
  # the groups claim through token introspection. oauth2-proxy uses the ID
  # token and userinfo, Grafana the userinfo endpoint. If a future consumer
  # does need it, raising the provider cap is the fix.
}

# Per-environment audience scopes for the CLI clients.
#
# SECURITY-CRITICAL, and not obviously so. A Keycloak access token carries
# `aud: ["account"]` and names the requesting client only in `azp`, which is not
# what oauth2-proxy verifies — it checks `aud` against its own client ID. Without
# a mapper putting that ID into `aud`, every CLI token fails verification at the
# edge and nothing works.
#
# The tempting fix is to widen oauth2-proxy's allowance to `account` instead.
# Do not: *every* token issued in this realm carries that audience, so any realm
# token — Grafana's included — would become a valid Freepod credential for any
# user. See openspec design.md D3.
#
# These are also what separates the environments. freepod-cli-prod and
# freepod-cli-dev register identical loopback redirect URIs (a CLI binds an
# ephemeral port on 127.0.0.1, so there is nothing host-specific to key on), so
# the `aud` claim is the ONLY thing stopping a dev token from working on prod.
# Each CLI client must carry its own audience scope and never the other's.
resource "keycloak_openid_client_scope" "api_prod" {
  realm_id    = keycloak_realm.freepod.id
  name        = "freepod-api-prod"
  description = "Adds the freepod-prod audience to access tokens, so oauth2-proxy on ${var.prod_domain} accepts them as bearer credentials."

  # Rides along as a default scope; not something a client names in `scope`.
  # Mirrors the `groups` scope above.
  include_in_token_scope = false
}

resource "keycloak_openid_audience_protocol_mapper" "api_prod" {
  realm_id        = keycloak_realm.freepod.id
  client_scope_id = keycloak_openid_client_scope.api_prod.id
  name            = "freepod-prod-audience"

  # The client_id string, not the internal UUID.
  included_client_audience = keycloak_openid_client.freepod_prod.client_id

  # The access token is the one presented as a bearer credential and the only
  # one oauth2-proxy verifies, so this must be true or the mapper is inert.
  add_to_access_token = true
  add_to_id_token     = false
}

resource "keycloak_openid_client_scope" "api_dev" {
  realm_id    = keycloak_realm.freepod.id
  name        = "freepod-api-dev"
  description = "Adds the freepod-dev audience to access tokens, so oauth2-proxy on ${var.dev_domain} accepts them as bearer credentials."

  include_in_token_scope = false
}

resource "keycloak_openid_audience_protocol_mapper" "api_dev" {
  realm_id        = keycloak_realm.freepod.id
  client_scope_id = keycloak_openid_client_scope.api_dev.id
  name            = "freepod-dev-audience"

  included_client_audience = keycloak_openid_client.freepod_dev.client_id

  add_to_access_token = true
  add_to_id_token     = false
}

locals {
  # Authoritative default client scope set for every client below. Matches the
  # Keycloak defaults for an OIDC client, plus `groups`. Anything not listed
  # here is removed from the client on apply.
  #
  # The freepod-api-* audience scopes are deliberately NOT here. This local is
  # applied to freepod_prod, freepod_dev and grafana alike, so adding one would
  # hand every client both environments' audiences and destroy the isolation the
  # scopes exist to provide.
  default_client_scopes = [
    "acr",
    "email",
    "profile",
    "roles",
    "web-origins",
    keycloak_openid_client_scope.groups.name,
  ]
}

resource "keycloak_openid_client_default_scopes" "freepod_prod" {
  realm_id       = keycloak_realm.freepod.id
  client_id      = keycloak_openid_client.freepod_prod.id
  default_scopes = local.default_client_scopes
}

resource "keycloak_openid_client_default_scopes" "freepod_dev" {
  realm_id       = keycloak_realm.freepod.id
  client_id      = keycloak_openid_client.freepod_dev.id
  default_scopes = local.default_client_scopes
}

resource "keycloak_openid_client_default_scopes" "grafana" {
  realm_id       = keycloak_realm.freepod.id
  client_id      = keycloak_openid_client.grafana.id
  default_scopes = local.default_client_scopes
}

# CLI clients get the standard set plus EXACTLY ONE audience scope — their own.
# Listing the other environment's scope here would make a token minted against
# one environment valid on the other, which is the failure this whole
# arrangement exists to prevent.
resource "keycloak_openid_client_default_scopes" "freepod_cli_prod" {
  realm_id  = keycloak_realm.freepod.id
  client_id = keycloak_openid_client.freepod_cli_prod.id
  default_scopes = concat(
    local.default_client_scopes,
    [keycloak_openid_client_scope.api_prod.name],
  )
}

resource "keycloak_openid_client_default_scopes" "freepod_cli_dev" {
  realm_id  = keycloak_realm.freepod.id
  client_id = keycloak_openid_client.freepod_cli_dev.id
  default_scopes = concat(
    local.default_client_scopes,
    [keycloak_openid_client_scope.api_dev.name],
  )
}

# Optional scopes are requested by name at authorization time. `offline_access`
# is what lets a CLI store a refresh token that outlives the 30-minute SSO idle
# timeout — the realm sets offlineSessionIdleTimeout to 30 days with no maximum
# lifespan, so a stored credential stays valid as long as it is used monthly.
#
# Declaring these explicitly narrows Keycloak's default optional set (which also
# includes address, phone and microprofile-jwt) to what a CLI actually needs.
resource "keycloak_openid_client_optional_scopes" "freepod_cli_prod" {
  realm_id        = keycloak_realm.freepod.id
  client_id       = keycloak_openid_client.freepod_cli_prod.id
  optional_scopes = ["offline_access"]
}

resource "keycloak_openid_client_optional_scopes" "freepod_cli_dev" {
  realm_id        = keycloak_realm.freepod.id
  client_id       = keycloak_openid_client.freepod_cli_dev.id
  optional_scopes = ["offline_access"]
}

# The broker needs identity only: who (sub), their verified email and a display
# name. No groups, no roles, no audiences -- nothing that would describe the user
# beyond what the consent page lists, and no optional scopes either, so an
# `offline_access` refresh token can never be requested.
locals {
  app_auth_client_scopes = ["acr", "email", "profile"]
}

resource "keycloak_openid_client_default_scopes" "freepod_apps_prod" {
  realm_id       = keycloak_realm.freepod.id
  client_id      = keycloak_openid_client.freepod_apps_prod.id
  default_scopes = local.app_auth_client_scopes
}

resource "keycloak_openid_client_default_scopes" "freepod_apps_dev" {
  realm_id       = keycloak_realm.freepod.id
  client_id      = keycloak_openid_client.freepod_apps_dev.id
  default_scopes = local.app_auth_client_scopes
}

resource "keycloak_openid_client_optional_scopes" "freepod_apps_prod" {
  realm_id        = keycloak_realm.freepod.id
  client_id       = keycloak_openid_client.freepod_apps_prod.id
  optional_scopes = []
}

resource "keycloak_openid_client_optional_scopes" "freepod_apps_dev" {
  realm_id        = keycloak_realm.freepod.id
  client_id       = keycloak_openid_client.freepod_apps_dev.id
  optional_scopes = []
}
