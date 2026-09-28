## Why

Logging out of an auth-enabled app doesn't work in practice. `/.freepod/auth/logout` only expires the app's own session cookie, then redirects to the return target. When that target is protected, which it is for any app that isn't mostly public, the browser goes straight back through the broker. Keycloak still has a sign-in session and consent is already on record, so a new session for the same account is issued without a single prompt. The user can't sign out, and can't sign in as a different account. A user refused by an app's own authorization (for example the upgrader's `ALLOWED_EMAILS` 403) is stuck.

## What Changes

- **BREAKING (behavior):** `/.freepod/auth/logout` also ends the user's Freepod sign-in at the identity provider. The verifier still expires the session on the requesting host, but it now hands the browser to the broker instead of redirecting to the return target.
- The broker gains `GET /logout`. It confirms the host is an auth-enabled deployment (the same check sign-in makes), seals the host and return target into a short-lived `state`, and sends the browser to Keycloak's end-session endpoint with the broker's client ID and a fixed post-logout redirect URI.
- The broker gains `GET /signed-out`, Keycloak's post-logout landing. It opens the `state` and redirects to `https://<host><rd>`. When `state` is missing, expired or invalid, it shows a "You're signed out" page and doesn't redirect.
- Keycloak shows its own "Do you want to log out?" confirmation, in the Freepod login theme, because the broker keeps no ID token to pass as `id_token_hint`. We accept that page. The user signs back in, as any account, on Keycloak's login form.
- Sessions on other app hosts are **not** ended: each is a host-bound cookie the verifier checks without consulting Keycloak. Only the next pass through the broker is affected, and only once: after that one sign-in Keycloak has a session again.
- Keycloak clients `freepod-apps-prod` and `freepod-apps-dev` register exactly one valid post-logout redirect URI each: the broker's `/signed-out`.
- The deploy-to-freepod skill shipped with the CLI (`cli/src/freepod/assets/SKILL.md`) documents what logout now does.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `app-auth-verifier`: logout stops being single-host-only. The reserved `/.freepod/auth/logout` path hands off to the broker, and the "Logout ends the session on one host" requirement, which forbids ending the identity-provider sign-in, is replaced.
- `app-auth-broker`: new requirement for signing out at the identity provider (`/logout`, `/signed-out`, host check, sealed state, no open redirect).
- `keycloak-terraform-config`: the app-authentication clients each list exactly one valid post-logout redirect URI.

## Impact

- `app-auth/`: `verify.go` (logout handoff), `broker.go` (two routes, end-session URL from OIDC discovery), `pages.go` (signed-out page), tests including `traefik_test.go` for the new redirect. New app-auth image version.
- `tf/deps/keycloak-config/clients.tf`: `valid_post_logout_redirect_uris` on both app clients. Needs a `tf/deps` apply **before** the new app-auth image rolls out; otherwise Keycloak answers every logout with "Invalid redirect uri".
- `cli/src/freepod/assets/SKILL.md`: logout wording, and so a CLI release to ship it.
- Apps: none need changes. Existing `/.freepod/auth/logout?rd=…` links keep working and now actually sign the user out.
