# Design

## Context

See proposal.md for why. The facts this design rests on:

- **The provider is live** (`app-oidc-provider`, `app-oidc-chart-contract`). A
  deployment is a client when its template declares `sso.redirectPaths` and its
  release enables `sso.enabled`. The reconciler then publishes Secret
  `<deployment>-oidc` (`OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`) and
  injects `caelus.oidc.{issuer, clientId, secretName}`. PKCE (S256) is required,
  and the provider never sends a claim other than `sub`, `email`,
  `email_verified` and `name`.
- **Immich reads its settings from one file or from its database.** The catalog
  chart, which the `immich-sso` chart starts from, mounts a ConfigMap at
  `/config` and sets `IMMICH_CONFIG_FILE`. When a
  config file is set, Immich applies it on every start and its admin screens
  can't change the settings it holds. The file is plain YAML (JSON parses as
  YAML), with no environment interpolation, so a secret has to be written into
  it.
- **Immich's OAuth login** (v3.3.5, `auth.service.ts`):
  - It looks a user up by `oauthId` (the `sub`) first, then by email. An email
    match that already has a different `oauthId` is refused. Otherwise the
    `sub` is stored on that user, so once linked, the `sub` is pinned.
  - With `autoRegister: false`, which is not the default, an unknown user is
    refused and no account is created.
  - `roleClaim` (`immich_role`) and `storageQuotaClaim` (`immich_quota`) apply
    only when the claim is present.
  - PKCE is used whenever discovery advertises S256. The mobile app passes the
    state and verifier back to the server, which redeems the code.
  - On sign-out it sends the browser to the end-session endpoint with the ID
    token it received as `id_token_hint`. A configured `endSessionEndpoint` is
    used as is, with that parameter added.
- **Immich's first admin** is created by `POST /api/auth/admin-sign-up`, which
  works only while the instance has no admin. The catalog chart doesn't seed
  one, so on a fresh catalog Immich the first visitor creates the admin.
- **The mobile app's redirect is `app.immich:///oauth-callback`.** Immich can
  rewrite it to `https://<host>/api/oauth/mobile-redirect`, which then
  redirects to the app's scheme.
- **Browsers apply `form-action` to every redirect after a form POST**, not just
  the first. A consent POST that redirects to an `https` page, which then
  redirects to `app.immich:`, is blocked by the consent page's
  `form-action 'self' https:`. This was tested in Chromium. The provider adds
  a native scheme to `form-action` only when the redirect URI itself uses it.
- **Docmost seeds its owner the same way** (`products/docmost`): a `postStart`
  hook calls the app's first-run setup. Probes don't start until the hook
  finishes, so the pod isn't Ready and gets no traffic until the owner exists.
- **Plans are per product.** A new product needs its own plan and plan template
  before it can be deployed.

## Goals / Non-Goals

**Goals:**

- A tenant who deploys `immich-sso` signs in to the web UI and the mobile app
  with Freepod, as the instance's admin, without ever setting an Immich
  password.
- Only people the admin created in Immich can sign in. Nothing on Freepod's side
  decides access.
- The client secret exists only in the published Secret and in the pod's
  memory.
- Nothing under `products/immich`, and nothing about the catalog Immich
  product or its deployments, changes.

**Non-Goals:**

- **SSO for the catalog Immich product.** Promotion is its own change, once
  this one has been used on real phones. It moves the SSO support into the
  catalog chart and retires the copy.
- **Migrating existing Immich deployments** with password accounts to SSO.
- **Back-channel logout and the allowlist.** Both belong to the allowlist
  change.
- **Linking an existing password account from Immich's user settings.** With
  password login off, there is nothing to link.

## Decisions

### D1: A separate chart and a separate product

`products/immich/chart` at 0.2.7 is copied to `products/immich-sso/chart`,
renamed `immich-sso` and versioned 0.1.0. It keeps the same `ssh-sidecar`
dependency, and all SSO work happens in the copy. The copy keeps an
`sso.enabled` switch that is off by default, as `app-oidc-chart-contract`
requires, and with it off it renders as the chart it was copied from.

`immich-sso` is a separate product, created with `caelus` and visible only to
admins. Its template points at the `immich-sso` chart and sets
`sso.enabled: true` as a system value. Its user values schema is the
catalog's, which is the hostname only, so no tenant can turn SSO off.

The point is to experiment freely with no way of affecting the catalog Immich
chart or the deployments built from it. The cost is that the two charts drift
apart. The sandbox also gets new Immich releases only by hand, because the
upgrader works from the catalog files and this product isn't in them. That is
acceptable for an admin-only product with a short life. Promotion, a later
change, moves the SSO support into the catalog chart and retires the copy.

Rejected: **an SSO switch in the catalog chart**, off by default. Every edit
would land in the chart that live deployments are built from, and a mistake
there would reach them on their next upgrade.

### D2: The config file is rendered at pod start

The ConfigMap keeps the settings that aren't secret, as JSON. With SSO on, an
init container runs the Immich server image's own `node`, reads that JSON,
writes `oauth.clientSecret` from `OIDC_CLIENT_SECRET`, and writes the result to
a memory-backed `emptyDir`. The server mounts that `emptyDir` at `/config`
instead of the ConfigMap. Only the init container gets the Secret, and only
that one key (`secretKeyRef`). The server container never has it in its
environment.

This meets the chart contract's "re-apply on every start": the file is
rewritten from the Secret on each start, and Immich applies it on each start.

Rejected: **Helm `lookup` of the Secret.** It writes the secret into the
rendered manifest and the release record, and it renders nothing under
`helm template`. Also rejected: **settings in Immich's database through its
API or admin screens.** They aren't re-applied on start, and the owner could
turn auto-registration back on from the admin screen.

Using the server image avoids a new image to pin and keep up to date, and it
already has `node`.

### D3: Immich's settings with SSO on

| Setting | Value | Why |
| --- | --- | --- |
| `oauth.enabled` | `true` | |
| `oauth.issuerUrl` | `caelus.oidc.issuer` | Discovery provides the endpoints, S256 and RS256 |
| `oauth.clientId` | `caelus.oidc.clientId` | |
| `oauth.clientSecret` | from the Secret (D2) | |
| `oauth.scope` | `openid email profile` | |
| `oauth.signingAlgorithm` | `RS256` | The provider signs nothing else |
| `oauth.tokenEndpointAuthMethod` | `client_secret_post` | Immich's default, and one the provider accepts |
| `oauth.autoRegister` | `false` | Immich decides (D4) |
| `oauth.autoLaunch` | `true` | Freepod is the only way in, so the login page goes straight to it |
| `oauth.buttonText` | `Sign in with Freepod` | |
| `oauth.mobileOverrideEnabled` | `false` | D6 |
| `oauth.endSessionEndpoint` | D7 | |
| `passwordLogin.enabled` | `false` | D4 |

`roleClaim` and `storageQuotaClaim` keep Immich's defaults. The provider never
sends `immich_role` or `immich_quota`, so SSO can't make anyone an admin or
change a quota. Those stay decisions made inside Immich.

### D4: Immich decides who gets in, and password login is off

Auto-registration is off, so an account the admin didn't create is refused.
Inviting someone means creating their user in Immich's administration screen
under the email of their Freepod account. Their first sign-in links that user to
their Freepod subject by email, and the `sub` is pinned from then on.

Password login is off too. Immich requires a password when an admin creates a
user, and as long as password login works, that password is a way into the
user's account that the admin knows. With it off, the only credential is the
user's Freepod sign-in. It also closes the pre-created-account path in the
chart contract. Immich has no self-service sign-up, and its first-admin sign-up
is closed by D5.

Rejected: **keeping password login** for people without a Freepod account.
Registration is open and free, and keeping it would leave admin-known
passwords working.

### D5: The chart creates the owner's admin account

With SSO on, a `postStart` hook on the server container waits for
`/api/server/ping` and then calls `POST /api/auth/admin-sign-up` with
`caelus.owner.email`, a name taken from it, and a random password that is
thrown away. The password can never be used, because password login is off.
An answer saying an admin already exists counts as success, so restarts are
harmless. Any other failure fails the hook, which restarts the container and
tries again.

As with Docmost, probes don't start until the hook finishes, so no outside
request reaches a fresh instance before its admin exists. On first sign-in,
the owner's Freepod account links to that admin by email. The chart refuses to
render with SSO on and no `caelus.owner.email`.

### D6: The mobile app uses the native redirect directly

The template declares `sso.nativeRedirectUris: ["app.immich:///oauth-callback"]`
and Immich's mobile override stays off. The provider then sees the native URI
itself, so its consent page adds `app.immich:` to `form-action`, and a
first-time consent from the phone reaches the app.

Rejected: **Immich's `https://<host>/api/oauth/mobile-redirect` override**. It
would fit `sso.redirectPaths` alone, but the consent POST's redirect chain would
then reach `app.immich:` one hop later, and the consent page's `form-action`
would block it (see Context).

### D7: Signing out returns to Immich

`oauth.endSessionEndpoint` is
`<issuer>/oidc/logout?client_id=<clientId>&post_logout_redirect_uri=https://<host>/`.
Immich adds `id_token_hint`, which the provider checks against its own keys
whatever the token's expiry, so the redirect back to the instance's root is
honored. Signing out of Immich ends the Freepod session, as signing out of a
header-authenticated app does, and then shows the Immich login page.

Without the override, Immich would send no `client_id` or redirect, and the user
would end up on the broker's signed-out page.

### D8: Callback paths

`sso.redirectPaths: ["/auth/login"]`. The web client sends its login page as
the redirect URI. `/user-settings` is Immich's other callback, used to link an
existing account. It's left out per the Non-Goals, because one path fewer is
one place fewer a code can be delivered.

## Risks / Trade-offs

- **[The broker is down]** → No new sign-in succeeds, and with password login
  off there is no fallback. Existing web and mobile sessions are Immich's own
  and keep working. An operator can still reach the instance with Immich's
  `immich-admin` command inside the server pod.
- **[A Keycloak realm rebuild issues new subjects]** → Immich refuses the new
  `sub` for a user already linked to the old one, so the user is locked out
  until the admin unlinks them in Immich. It fails closed, which is the
  behavior the chart contract prefers.
- **[Signing out of Immich signs out of all of Freepod]** → This matches
  header-authenticated apps. Keycloak asks the user to confirm first.
- **[Removing a user's Freepod access doesn't end their Immich sessions]** →
  Accepted until the allowlist change brings back-channel logout. Immich
  supports it.
- **[The seeded admin's name comes from an email address]** → The owner can
  rename themselves in Immich.

## Migration Plan

Additive. Nothing changes for the catalog product or existing deployments.

1. Publish the `immich-sso` chart (CI, on merge).
2. Create `immich-sso` on dev with `caelus`, with its template and a plan.
   Deploy it, then verify the web, mobile and sign-out flows.
3. Create the same product on prod, still admin-only.

Rollback: delete the `immich-sso` deployments and product, and the chart
directory if the experiment ends. The catalog product was never involved.
