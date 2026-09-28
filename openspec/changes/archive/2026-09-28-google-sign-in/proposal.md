## Why

Signing up for Freepod today means creating yet another password. Offering "Sign in with
Google" alongside local registration removes that step for the many prospective users who
already have a Google account, and Keycloak supports it natively — no Freepod code has to
change for it.

## What Changes

- Register Google as an OIDC identity provider on the `freepod` realm, managed in
  `tf/deps/keycloak-config/`, with its client ID and secret supplied through
  `secrets.auto.tfvars`.
- Trust the email address Google asserts, so an account created through Google needs no
  Keycloak verification email.
- Keep Keycloak's default first-login flow for a Google identity whose email already belongs
  to a Freepod account: the user confirms the link and proves ownership of the existing
  account (emailed link or its password), after which both sign-in methods reach the same
  account. No automatic linking.
- Import profile attributes from Google once, at account creation (`IMPORT` sync mode), so a
  later change on the Google side never rewrites the Keycloak email that Freepod resolves
  accounts by.
- Style the Google button in the `freepod` login theme (CSS only; the parent theme already
  renders it).
- Name Google as a source of account data in the privacy policy.

Out of scope: any change to the API, UI, oauth2-proxy or app-auth; other social providers;
supporting email-address changes, which belongs to `keycloak-subject-join-key`.

## Capabilities

### New Capabilities

- `keycloak-google-identity-provider`: Google as an identity provider on the `freepod`
  realm — its registration, email trust, sync mode, how a Google identity meets an existing
  account, and its reach across every client in the realm.

### Modified Capabilities

- `keycloak-user-realm`: the email-verification requirement now recognizes a verified email
  asserted by a trusted identity provider as satisfying verification, instead of requiring
  every new account to click a Keycloak verification link.

## Impact

- **Terraform**: `tf/deps/keycloak-config/` (new identity-provider resource and variables),
  `tf/deps/main.tf` and `tf/deps/variables.tf` (pass the Google credentials through).
- **Keycloak image**: `tf/deps/keycloak/theme/freepod/login/resources/css/login.css`;
  rebuilt with `./scripts/build-images.sh --keycloak`.
- **External**: a Google Cloud project with an OAuth consent screen and web client; brand
  verification requires public privacy-policy and terms URLs on `freepod.eu`.
- **Legal**: `legal/privacy-policy.md` (data source, new effective date).
- **Every client in the realm** gains the Google option — the oauth2-proxy clients, the CLI
  clients, the app-auth broker and Grafana — with no per-client configuration. Access to
  `dev.freepod.eu` and Grafana stays governed by group membership.
- **Not affected**: the Freepod API and its data model. A Google user is an ordinary
  `freepod`-realm user with a Keycloak subject and an email claim.
