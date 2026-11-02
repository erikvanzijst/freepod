# Design

## Context

One Keycloak instance (`tf/deps/keycloak`, namespace `keycloak`) serves the
`freepod` realm for prod and dev alike. It runs one replica, with no probes, no
resource limits and the default RollingUpdate strategy. Its image is
`ghcr.io/erikvanzijst/freepod/keycloak:latest`, built from `quay.io/keycloak/keycloak:24.0`
with the Freepod theme copied in. Realm configuration is applied over the admin
API by `tf/deps/keycloak-config`, with provider `keycloak/keycloak ~> 5.7.0`.

The direct consumers of Keycloak are:

- oauth2-proxy (browser sessions, and CLI bearer tokens through
  `skip-jwt-bearer-tokens`, which forwards the token's `sub` as
  `X-Auth-Request-User`)
- the app-auth broker
- Grafana
- the `freepod` CLI

Catalog apps that use "Sign in with Freepod" talk only to the broker.

Facts established before this change by running 26.8.1 against a copy of the
prod database, and by reading the upstream source and upgrade notes:

- The migration from 24.0.5 runs every model step through 26.8.0 without errors.
  It adds `basic` to all seven Freepod clients.
- Without `basic`, `sub` disappears from access tokens only. ID tokens and
  userinfo keep it. Under caller-identity-resolution, a request with no subject
  resolves by email alone, so the failure is silent, not a 401.
- The account theme's parent `keycloak.v2` is gone in 26. Keycloak logs
  `Failed to find ACCOUNT theme freepod, using built-in themes` and serves the
  stock console. The new `keycloak.v3` console is PatternFly 5 and ships a dark
  mode. Our `account.css` has 62 PatternFly 4 (`pf-c-`) selectors.
- The `keycloak.v2` login theme is still PatternFly 5. Several things changed:
  - The Google button now renders in the main body, with its own `<img>`,
    its own label and a native divider.
  - Our `::before` "or" and `::after` "Sign in with Google" would duplicate
    them, and the `.pf-v5-c-login__main-footer-links` selectors no longer match.
  - About twenty pages that used to fall back to the PatternFly 4 `keycloak`
    theme are now native `keycloak.v2` pages.
- The four email templates we override are unchanged upstream, apart from a
  `lang` attribute on `<html>`.
- The registration form now collects only email, first name and last name.
- Port-less loopback redirect matching, which CLI login depends on, is still in
  26.8.1's `RedirectUtils`.
- Postgres 17 is supported.

## Goals / Non-Goals

**Goals:**

- Reach 26.8.1 in one maintenance window, with a rollback that is rehearsed,
  not theoretical.
- Leave no Freepod-visible regression. Tokens, theme coverage and sign-in flows
  should behave as on 24 or better.
- Remove the version-specific workarounds that only existed for 24: the
  provider cap and the hostname v1 options.

**Non-Goals:**

- Memory requests and limits. Keycloak sits at ~3.6 GiB with none set. Sizing
  it is a separate change, made once 26's footprint has been observed.
- A second replica or any HA setup.
- Adopting new 26 features: organizations, passkeys, lightweight tokens.
- Changing the oauth2-proxy, broker or CLI code. None of them needs it.

## Decisions

### D1. Upgrade 24.0.5 → 26.8.1 directly

Keycloak applies every intermediate model migration on startup, and the
rehearsal showed all of them succeed on our data. Stepping through 25 and then
26.0 would mean three windows, for no extra safety.

### D2. Rehearse on a copy of the prod database before every production step

There is no staging Keycloak, because dev and prod share the instance. The
rehearsal works like this:

- Restore a `pg_dump` into a throwaway Postgres.
- Run the exact candidate image against it.
- Use it for the migration check, the theme review and the rollback drill.

The rehearsal instance must be reachable from the browser used for review.
Docker-published ports land on the Docker host, not on this devcontainer's
`localhost`.

The dump contains user PII. It lives only in the gitignored `var/` and is
deleted after cutover.

### D3. The `basic` scope goes into the authoritative scope lists

Add `basic` to `local.default_client_scopes` and to
`local.app_auth_client_scopes` in `scopes.tf`.

Alternative rejected: stop managing default scopes. Those authoritative lists
are what keep each CLI client to exactly one environment's audience.

The scope exists only on 26, so this edit must not be applied while the server
is still on 24. See the Migration Plan.

### D4. Hostname v2 with a full URL

Set `KC_HOSTNAME=https://keycloak.freepod.eu` and drop `KC_HOSTNAME_URL`,
`KC_HOSTNAME_ADMIN_URL`, `KC_HOSTNAME_STRICT` and
`KC_HOSTNAME_STRICT_BACKCHANNEL`. The admin console uses the same URL, so
`KC_HOSTNAME_ADMIN` is unnecessary.

`hostname-backchannel-dynamic` keeps its default, `false`. Every consumer
already uses the public URL, including oauth2-proxy, the broker, Grafana and
the Terraform provider. Back-channel logout runs from Keycloak to the broker,
so it is unaffected.

Drop `--hostname-debug=true`. It publishes a diagnostics page and was only
there for the original setup. Turn it on temporarily when needed.

`KC_PROXY_HEADERS=xforwarded` and `KC_HTTP_ENABLED=true` stay as they are.

### D5. Health endpoints, a startup probe, and readiness and liveness probes

Enable `KC_HEALTH_ENABLED=true` and probe on the management port 9000, which
is not exposed by the Service or Ingress:

- **Startup probe:** `/health/started`, with enough failures allowed to cover
  a cold start plus migration.
- **Readiness probe:** `/health/ready`.
- **Liveness probe:** `/health/live`.

The startup probe is what stops liveness from killing a pod in the middle of a
migration, which is the failure 26's early-open ports were designed to avoid.
Readiness also closes the ~25 s window of 502s after a restart seen on 24, and
gives `keycloak_config` applies something to wait on.

### D6. `Recreate` strategy

Recreate guarantees the Keycloak spec's no-overlap rule on every rollout, not
just when someone remembers to scale to 0.

Cost: every pod-template change has a startup's worth of downtime, about
15–30 s. With one replica and in-memory sessions, 24 already loses everyone's
session on restart, so 26 is still better on net.

Alternative rejected: RollingUpdate plus a manual scale-down for upgrades. It
relies on discipline, and it would put two different versions on one schema if
someone forgot.

### D7. Pin the image tag and stop using `:latest`

Set `FROM quay.io/keycloak/keycloak:26.8.1`. Publish the image under a
versioned tag, `keycloak:26.8.1-<n>`, where `<n>` increases for theme-only
rebuilds. Point `keycloak_image` at that tag.

Today's `:latest` with `imagePullPolicy: Always` means any pod restart can
silently pick up a different server version. Registry tags are never
overwritten.

### D8. Account theme: rebuild on `keycloak.v3` and brand through PatternFly variables

`parent=keycloak.v3`, keeping `logo` and `logoUrl`. Use PatternFly 5's dark
palette as the base: `darkMode=true` would only follow the OS preference, so
`darkMode=false` plus a one-line script that always applies PatternFly's dark
class. Then rewrite `account.css` to set PatternFly 5 global CSS variables
(surface, text, accent, fonts, border radius), with as few per-component
selectors as possible.

The 24 stylesheet broke because it overrode per-component class names, and a
token-level override survives upstream markup changes far better.

The console's layout is upstream's. In particular, the 24 console's welcome page
(three cards: Personal info, Account security, Applications) is gone, and
`keycloak.v3` opens on Personal info with a sidebar listing the same pages.
The home route is fixed in the bundle; `content.json` can only add pages under
`#/content/<id>`, so the welcome page can't come back through the theme. Its
absence on prod after cutover is expected, not a regression.

Alternative rejected: a custom account UI (`@keycloak/keycloak-account-ui`,
Keycloakify, or a fork of the React app), which would also bring back the
welcome page. It is a large maintenance surface, rebuilt on every Keycloak
upgrade, for a console few users open.

### D9. Login theme: style Keycloak's native Google button and divider

Keep `parent=keycloak.v2`.

- Delete the pseudo-element "or" and label.
- Restyle the native divider and the `#social-google` button to Google's dark
  button spec.
- Use upstream's `img/social/google.svg` if it is the official four-color G;
  otherwise keep ours by overriding that one resource path.

Then review every page listed in the keycloak-theme spec in the rehearsal
instance. Ten or more of them render a different template than on 24.

### D10. Accept upstream's verify-first registration

Keep Keycloak 26's default: no password on the registration form, email
verification first, then the password.

Alternative rejected: "Always set password on register form". Upstream has
deprecated it, and it brings back the window where an unverified account has a
working credential. This follows the rule of fitting Freepod to the
application's intended flow.

### D11. Raise the provider after the server

Bump to `~> 5.10` in both `providers.tf` and `keycloak-config/versions.tf`,
refresh `.terraform.lock.hcl`, and update the comments that justify the 5.7 cap
or cite Keycloak 24 behavior:

- `providers.tf`
- the `groups` mapper's `add_to_token_introspection` note in `scopes.tf`
- the default-scope inventory in `scopes.tf`
- the `RedirectUtils` note in `clients.tf`

5.9 and later drop support for servers older than 26, so the bump applies only
once the server is on 26.

### D12. Hide the username from users through the realm's user profile

The username is always the email address (`registration_email_as_username`).
The 24 console hid it itself whenever that setting was on. The `keycloak.v3`
console shows every attribute the user profile lets users view, so Personal
info gains a read-only "Username" field repeating the email.

Manage the realm's user profile in Terraform (`keycloak_realm_user_profile`),
as Keycloak 26.8.1's default profile with `username` limited to
`view = ["admin"]`, `edit = ["admin"]`. The realm has no profile of its own
today, so it runs on Keycloak's built-in default. The resource is
authoritative and replaces the whole profile, so it restates the four default
attributes (`username`, `email`, `firstName`, `lastName`) and the
`user-metadata` group. Once stored, the profile no longer changes with
Keycloak upgrades.

Verified in the rehearsal with provider 5.10.0:

- Applied over the default profile, a second plan shows no changes.
- The stored profile differs from the default only in the username
  permissions, and in length limits being stored as strings. Keycloak still
  enforces them: a 300-character first name is rejected.
- Personal info shows email, first name and last name. Saving works, a new
  registration still gets its email as username, and access tokens still carry
  `preferred_username`.

Applied in phase 2, after the server is on 26. It isn't needed on 24, whose
console hides the field.

Alternative rejected: hiding the field with CSS in the account theme. It
depends on the console's markup and fails silently when that changes, and it
leaves the server stating that users can see the attribute.

## Risks / Trade-offs

- **The server and its config get out of step during cutover.** For example,
  `keycloak_config` is applied with the old scope lists, or before the server
  is on 26. → Mitigation:
  - Apply the server first, alone (`-target=module.keycloak`).
  - Then apply the config from the same branch.
  - Never apply `tf/deps` from an older checkout after cutover.
- **Provider 5.10 configured against a 24 server during the targeted apply.**
  → Mitigation: rehearse the targeted apply's plan against the rehearsal
  instance first. If the provider won't initialize against 24, do phase 1 from
  a checkout that still pins 5.7.
- **Theme regression on a page nobody reviewed.** → Mitigation: the
  keycloak-theme spec lists every page, and each one is checked in a browser in
  the rehearsal, light and dark, desktop and mobile width.
- **Google sign-in and account linking can't run in the rehearsal**, because
  Google's redirect URI is bound to `keycloak.freepod.eu`. → Mitigation: those
  are the first checks run on prod after cutover, and the rollback is ready if
  they fail.
- **A liveness or startup probe kills a pod mid-migration.** → Mitigation:
  generous startup-probe thresholds, sized from the rehearsal's measured
  bootstrap time with headroom.
- **Everyone is signed out once at cutover.** → Accepted: 24 sessions can't be
  migrated. CLI offline sessions survive. Schedule the window at low traffic.
- **The new sign-up flow confuses people expecting to choose a password up
  front.** → Mitigation: update the get-started docs, and check that the
  verification email and set-password page read clearly in the theme review.

## Migration Plan

1. **Rehearse.**
   - Dump the prod Keycloak DB into `var/` and restore it into a throwaway
     Postgres.
   - Run the candidate image against it.
   - Confirm all migration steps succeed and record the bootstrap time.
   - Do the theme review.
   - Request tokens from a CLI client and confirm `sub` is present.
2. **Publish** the versioned image tag. Merge is not needed for this.
3. **Window, phase 1 (server).**
   - Take a fresh `pg_dump` of the prod Keycloak DB.
   - `terraform apply -target=module.keycloak` with the new image, env,
     probes and `Recreate`.
   - Wait for Ready and check the discovery document's `issuer`.
4. **Window, phase 2 (config).**
   - `terraform init -upgrade`, then `terraform plan` in `tf/deps`.
   - Expected: no scope removals, one new `keycloak_realm_user_profile`
     (D12), and no drift beyond provider-default normalization. Investigate
     anything else before applying.
   - Apply.
5. **Verify on prod.** For each item below, check both prod and dev:
   - dashboard sign-in and sign-out
   - registration with verify-first, then set password
   - password reset email
   - Google sign-in, and linking an existing account
   - `freepod login` (loopback, and `--device`)
   - an existing cached CLI refresh token
   - API calls carrying `X-Auth-Request-User`
   - an SSO app sign-in through the broker, and back-channel sign-out
   - Grafana sign-in with the group gate
6. **Rollback** (any step after 3):
   - Scale Keycloak to 0.
   - Drop and recreate the `keycloak` database, then restore the step-3 dump.
   - Point `keycloak_image` back at the 24 image digest currently running, and
     revert the env block.
   - Apply `-target=module.keycloak`.
   - If phase 2 already ran, revert the scope and provider changes as well.

   Users sign in again afterwards.
7. **After a soak with no rollback**, delete the dumps from `var/`.
