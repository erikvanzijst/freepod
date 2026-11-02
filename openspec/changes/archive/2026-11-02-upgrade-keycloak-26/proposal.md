# Proposal

## Why

Freepod's single Keycloak instance runs 24.0.5 (mid-2024). It serves both
environments, every Freepod sign-in, the CLI, Grafana and the app-auth broker.
It is two major versions behind the current 26.8.1, so it gets no more security
fixes, and the Terraform provider is held at 5.7 to keep working with it.
Upgrading is not a drop-in image bump. Several of Freepod's own settings and
customizations stop working or silently change behavior on 26, so the upgrade
has to land together with those fixes.

## What Changes

- Run Keycloak **26.8.1**, pinned to an exact version instead of the floating
  `24.0` tag, and upgrade it with no overlap between the old and new versions.
  The database migration is one-way, so a database backup comes first.
- **BREAKING (for Terraform):** every realm client carries Keycloak's `basic`
  client scope. Since 25, that scope is what puts `sub` into access tokens. The
  migration adds it, but our authoritative default-scope lists would strip it
  on the next apply. CLI bearer tokens would then reach the edge without a
  subject, and the API would resolve callers by email alone.
- Replace the removed hostname v1 options (`KC_HOSTNAME_URL`,
  `KC_HOSTNAME_ADMIN_URL`, `KC_HOSTNAME_STRICT*`) with the v2 `KC_HOSTNAME`.
  Rename the deprecated `KEYCLOAK_ADMIN*` variables to
  `KC_BOOTSTRAP_ADMIN_*`.
- Enable Keycloak's health endpoints and add readiness and liveness probes.
  On 26, the HTTP port opens before startup has finished.
- **Account theme rebuilt** on `keycloak.v3`. Its parent `keycloak.v2` no
  longer exists, and today's stylesheet targets PatternFly 4. Without the
  rebuild, Keycloak falls back to the stock, unbranded console.
- **Login theme reworked** for the 26 `keycloak.v2` templates. The Google
  button now ships its own logo, label and "or" divider, which our stylesheet
  would duplicate. Pages that used to fall back to the old PatternFly 4 theme
  are now PatternFly 5 and get the Freepod styling too.
- **The realm's user profile is managed in Terraform**, with the username
  visible to administrators only. The username is always the email address;
  the 24 console hid it, but the 26 console shows it as a separate,
  read-only field.
- Raise the Terraform provider from `~> 5.7.0` to the current 5.x, after the
  server is on 26. The 5.7 cap existed only for Keycloak 24, and 5.9+ drop
  support for anything older than 26.
- **User-visible:**
  - Self-registration follows Keycloak 26's default flow: the form collects
    email and name, and the password is set after the email is verified.
  - Everyone signs in once more at cutover. In-memory 24 sessions cannot be
    migrated.
  - From then on, sign-ins survive Keycloak restarts, because sessions are
    stored in the database.

## Capabilities

### New Capabilities

- `keycloak-theme`: The Freepod branding of Keycloak's login, account and email
  pages. Each theme resolves on the running server and covers every page a user
  can reach, and the Google sign-in option follows Google's branding, shown
  exactly once.

### Modified Capabilities

- `keycloak-deployment`:
  - The configuration variables change to the v2 hostname and bootstrap-admin
    names.
  - Health probes become real.
  - The version is pinned and upgraded without two versions sharing one
    database.
  - Sign-in sessions persist across restarts.
- `keycloak-user-realm`:
  - Every client issues access tokens that carry the subject.
  - Self-registration verifies the email before a password is set.
  - Users are not shown a username; the realm's user profile is managed by
    Terraform.
- `oauth2-token-auth`: CLI access tokens must carry `sub`, the claim the edge
  forwards as the caller's subject.
- `keycloak-terraform-config`: The provider version must support the running
  server's major version.

## Impact

- `tf/deps/keycloak/`:
  - `Dockerfile`: the base image.
  - `keycloak.tf`: env, args, probes, upgrade strategy.
  - `theme/freepod/account/`: rewritten.
  - `theme/freepod/login/`: the CSS reworked and checked page by page.
  - `theme/freepod/email/`: only re-checked.
- `tf/deps/keycloak-config/scopes.tf`, `versions.tf` and a new
  `user-profile.tf`, and
  `tf/deps/providers.tf` with its lock file.
- `openspec/specs/keycloak-deployment/spec.md`: its header must be fixed to
  `## Requirements` (it currently parses as zero requirements) before this
  delta can archive.
- Operations: one maintenance window on the shared instance, which signs
  every user out of the dashboard, Grafana and broker-signed-in apps.
  CLI refresh tokens (offline sessions) survive. Catalog apps that use "Sign
  in with Freepod" are reached only through the app-auth broker and need no
  change.
- Docs: the sign-up step in `ui/docs/apps/get-started.md`.
