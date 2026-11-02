# Tasks

## 1. Spec housekeeping and rehearsal environment

- [x] 1.1 Change the stray `## ADDED Requirements` header in `openspec/specs/keycloak-deployment/spec.md` to `## Requirements`, and correct its `auth-system` namespace references to `keycloak`; verify `openspec list --specs` reports a non-zero requirement count for `keycloak-deployment`
- [x] 1.2 Write a rehearsal script under `var/` that dumps the prod Keycloak DB (`pg_dump -Fc` from the `postgres` pod), restores it into a throwaway `postgres:17-alpine` container and starts a given Keycloak image against it, reachable from the review browser (D2); verify the script brings up a Ready instance and that the realm list includes `freepod`

## 2. Server image and deployment

- [x] 2.1 Change `tf/deps/keycloak/Dockerfile` to `FROM quay.io/keycloak/keycloak:26.8.1` and update its comments that cite 24; verify `docker build` succeeds
- [x] 2.2 In `tf/deps/keycloak/keycloak.tf`, replace the hostname v1 variables with `KC_HOSTNAME=https://keycloak.${var.domain}`, rename `KEYCLOAK_ADMIN*` to `KC_BOOTSTRAP_ADMIN_*`, add `KC_HEALTH_ENABLED=true`, drop `--hostname-debug=true`, and rewrite the comments for the new options (D4); verify by running the rehearsal against the built image with this env: startup logs show no unknown, removed or deprecated option warnings, and the discovery `issuer` is the public URL
- [x] 2.3 Add a startup probe on `/health/started`, a readiness probe on `/health/ready` and a liveness probe on `/health/live`, all on management port 9000, with the startup threshold sized from the rehearsal's measured bootstrap time plus headroom (D5); verify the rehearsal pod only reports Ready after "Bootstrap completed" is logged
- [x] 2.4 Set the Keycloak deployment strategy to `Recreate` (D6); verify `terraform plan -target=module.keycloak` shows the strategy change and no other unexpected diff
- [x] 2.5 Change the `keycloak_image` default in `tf/deps/keycloak/variables.tf` (and any tfvars) from `:latest` to a versioned tag `26.8.1-1`, and make `scripts/build-images.sh --keycloak` push that tag (D7); verify the script's dry-run or help output shows the versioned tag and that `:latest` is no longer referenced by Terraform
- [x] 2.6 Update the Keycloak sections of `tf/deps/README.md` (version, probes, Recreate, image tag, upgrade and rollback procedure in brief, linking this change's design); verify the README contains no remaining 24-specific statements

## 3. Account theme

- [x] 3.1 Rebase `theme/freepod/account/theme.properties` on `keycloak.v3` with `darkMode=false` and a script that always applies PatternFly's dark class, keeping `logo` and `logoUrl` (D8); verify in the rehearsal that the log has no `Failed to find ACCOUNT theme` entry and that the console shows the Freepod logo
- [x] 3.2 Rewrite `account/resources/css/account.css` against PatternFly 5, mainly through global CSS variables (surface, text, accent, fonts, radius about 10–12px); verify in the browser that Personal info, Account security (signing in, device activity), Linked accounts and Applications match the Freepod look in both desktop and mobile widths, with screenshots saved under `var/`

## 4. Login and email themes

- [x] 4.1 Rework the identity-provider section of `login/resources/css/login.css`: remove the pseudo-element "or" and label, restyle the native divider and `#social-google` button to Google's dark button spec, and decide whether to keep `img/google-g.svg` by comparing it with upstream's `img/social/google.svg` (D9); verify on the rehearsal sign-in page that there is exactly one G mark, one "Sign in with Google" label and one divider
- [x] 4.2 Review and fix the styling of every page the keycloak-theme spec lists: sign in, register, reset password, update password, verify email, update profile, account-link confirmation, device-code entry, error page; verify each in the browser at desktop and mobile width, with screenshots saved under `var/`
- [x] 4.3 Add `lang`/`dir` to `email/html/template.ftl` to match upstream, then trigger the verification and password-reset emails in the rehearsal (the realm SMTP pointing at a local catcher); verify both render with the Freepod layout and button
- [x] 4.4 Update the sign-up step in `ui/docs/apps/get-started.md` for the verify-first flow (D10); verify the docs build succeeds

## 5. Realm configuration and provider

- [x] 5.1 Add `basic` to `local.default_client_scopes` and `local.app_auth_client_scopes` in `tf/deps/keycloak-config/scopes.tf`, and update the scope-inventory comment (D3); verify, by running `terraform plan` against the rehearsal instance, that no client's default scopes change
- [x] 5.2 Raise the `keycloak/keycloak` provider to `~> 5.10` in `tf/deps/providers.tf` and `tf/deps/keycloak-config/versions.tf`, refresh `.terraform.lock.hcl`, and rewrite the comments that justify the 5.7 cap or cite Keycloak 24 behavior (`providers.tf`, the `groups` mapper note in `scopes.tf`, the `RedirectUtils` note in `clients.tf`) (D11); verify `terraform init -upgrade` succeeds and the plan against the rehearsal instance shows no unexplained drift
- [x] 5.3 Determine against a Keycloak 24 instance (the rehearsal run on the old image) whether provider 5.10 initializes for a `-target=module.keycloak` plan; verify the outcome is recorded in the cutover runbook (6.1) as either "single checkout" or "phase 1 from a 5.7 checkout"
- [x] 5.4 In the rehearsal, obtain tokens through `freepod-cli-dev` (device flow) and decode the access token; verify it carries `sub`, `email`, `groups` and the `freepod-dev` audience
- [x] 5.5 Add `tf/deps/keycloak-config/user-profile.tf` with a `keycloak_realm_user_profile` for the `freepod` realm: Keycloak 26.8.1's default profile (`username`, `email`, `firstName`, `lastName`, group `user-metadata`), with `username` view and edit limited to `admin` (D12); verify against the rehearsal instance that apply then plan shows no changes, that Personal info shows no username field, and that a 300-character first name is still rejected

## 6. Cutover

- [x] 6.1 Write the cutover and rollback runbook in `var/keycloak-26-cutover.md` from the design's Migration Plan, including the exact commands, the running 24 image digest to roll back to, and the 5.3 outcome; verify by doing a full rollback drill on the rehearsal (restore dump, then the 24 image) that ends in a working 24 sign-in
- [x] 6.2 Publish the versioned Keycloak image (`26.8.1-1`); verify `docker pull` of the tag succeeds and its digest is recorded in the runbook
- [x] 6.3 Take a fresh prod `pg_dump`, then run phase 1 (`terraform apply -target=module.keycloak`); verify the pod is Ready, all migration steps logged, and the discovery `issuer` is `https://keycloak.freepod.eu/realms/freepod`
- [x] 6.4 Run phase 2 (`terraform plan`, then apply in `tf/deps`); verify the plan removes no client scope before applying, and the apply completes with no errors

## 7. Production verification

- [x] 7.1 On prod and dev, verify dashboard sign-in and sign-out, and that a session survives a Keycloak pod restart
- [x] 7.2 Verify the full registration flow (verify-first, then set password) and the password-reset email on prod
- [x] 7.3 Verify Google sign-in for a new account, and linking for an existing password account, still requires emailed or password proof
- [x] 7.4 Verify `freepod login` via loopback and via `--device`, plus a pre-upgrade cached refresh token, against prod; verify `freepod` API calls succeed and that the API logs or records the caller's subject (non-empty `X-Auth-Request-User`)
- [x] 7.5 Verify an SSO app (immich-sso or discourse-sso) sign-in through the broker, and that signing out at Keycloak signs the browser out of that app via back-channel logout
- [x] 7.6 Verify Grafana sign-in for a `freepod-observability` member, and denial for a non-member
- [x] 7.7 Verify the account console, sign-in page and an email on prod against the rehearsal screenshots (the console opens on Personal info, not the 24 welcome page; D8)

## Workflow follow-up

- After a soak with no rollback, delete the database dumps from `var/`.
- Archive the change, syncing delta specs into the main specs.
- Follow-up change: Keycloak memory request and limit, sized from observed 26 usage.
