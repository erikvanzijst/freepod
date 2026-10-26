# Proposal

## Why

Sign in with Freepod reaches tenant apps only as trusted headers behind Traefik
forward-auth. That suits `custom` apps and App Studio, but not the catalog: none
of its apps reads identity headers, and their mobile and desktop clients cannot
pass a forward-auth redirect. Most of them do speak OpenID Connect: Immich,
Nextcloud, Vaultwarden, Discourse, BookStack, PhotoPrism and tuwunel all accept
a generic OIDC provider.

Pointing them at Keycloak directly would need a Keycloak client, or at least a
redirect URI, per deployment. Keycloak's wildcards cannot express
`<app>.<sub>.freepod.eu` or custom domains, and thousands of per-deployment
clients are exactly the per-tenant identity-provider configuration the
platform avoids. The broker already stands between tenant apps and Keycloak
with one client per environment, checks which hosts are deployments, and
records consent. It can face apps as an OpenID Provider in its own right.

This is the first of several changes towards catalog SSO. It ships the provider
and the platform plumbing only; no chart uses it yet.

## What Changes

- **The broker becomes an OpenID Provider** at its existing login host. The
  issuer is `https://login.<domain>`, with discovery, authorization, token,
  userinfo, JWKS and end-session endpoints, and the authorization code flow
  only. Upstream nothing changes: the broker still signs users in through its
  one Keycloak client, and reuses its consent page and consent records.
- **Every opted-in deployment is its own OIDC client with no client record.**
  The client ID is the deployment's ID. The client secret is an HMAC of that ID
  under a per-environment key that the reconciler and the broker share. Nothing
  is registered in Keycloak or stored per deployment.
- **A deployment opts in with `sso.enabled`**, read like `auth.enabled`: the
  template's system value over the release's user value, from the release the
  deployment serves. It is independent of `auth.enabled`.
- **Redirect URIs are derived, not registered.** Any `https` URI on the
  deployment's own hostname is accepted, plus the exact URIs the template lists
  as a system value for native clients (such as `app.immich:///oauth-callback`).
- **The reconciler publishes the credentials** for an SSO-enabled deployment in
  a Kubernetes Secret in its namespace, and injects only the issuer, client ID
  and Secret name into the chart values.
- **ID tokens are RS256 JWTs** with `aud` set to the deployment ID, so a token
  issued to one app is useless at another. They carry `sub` (the Keycloak
  subject, the same value as `X-Freepod-User`), `email`, `email_verified` and
  `name`.
- Nothing changes for header-based authentication, the verifier, existing
  deployments or any chart.

## Capabilities

### New Capabilities

- `app-oidc-provider`: the broker's OpenID Provider endpoints, client
  authentication, redirect-URI rules, tokens and claims.
- `app-oidc-chart-contract`: how a deployment opts in, and what the reconciler
  gives an SSO-enabled chart.

### Modified Capabilities

- `app-auth-data-model`: a table for OIDC authorization codes, and the
  service role's grants on it.

## Impact

- `daemons/app-auth/`: the provider endpoints (a new `provider.go` and tests),
  the `sso.enabled` eligibility query and the code table in `store.go`, new
  configuration in `main.go`, README. A new `daemons` image version.
- `api/`: an Alembic migration for `app_auth_oidc_code`; settings for the
  issuer and the client keyring; the reconciler's Secret and `caelus.oidc`
  override; tests.
- `tf/app/`: generated client keyring and signing key, passed to both the
  API and app-auth; the role's grants in `app-auth-bootstrap.sql`; the app-auth
  image pin.
- `AGENTS.md`: the Sign in with Freepod paragraph points at the new specs.
- Unchanged: Keycloak configuration, the verifier, the `custom` and
  `appstudio` charts, the catalog, the UI and the `freepod` CLI.
