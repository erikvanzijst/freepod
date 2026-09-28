## 1. Google Cloud

- [x] 1.1 Configure the OAuth consent screen for Freepod (external, scopes `openid email profile`, `freepod.eu` as authorized domain, privacy-policy and terms URLs on `freepod.eu`) and verify its publishing status is "In production", not "Testing".
- [x] 1.2 Create a web OAuth client with redirect URI `https://keycloak.freepod.eu/realms/freepod/broker/google/endpoint`, and verify the client ID and secret are stored in `tf/deps/secrets.auto.tfvars` only.
- [x] 1.3 Submit brand verification (domain ownership of `freepod.eu` via Search Console) and record the submission; approval is not a blocker for the tasks below.

## 2. Terraform

- [x] 2.1 Add sensitive `google_client_id` / `google_client_secret` variables to `tf/deps/variables.tf` and `tf/deps/keycloak-config/variables.tf`, pass them into `module.keycloak_config` in `tf/deps/main.tf`, and verify `terraform validate` passes.
- [x] 2.2 Add a `keycloak_oidc_google_identity_provider` on the `freepod` realm with `trust_email = true`, `sync_mode = "IMPORT"` (commented as pinned until `keycloak-subject-join-key` lands), the stock `first broker login` flow and no identity-provider mappers, and verify `terraform plan` in `tf/deps/` shows only that resource being added.

## 3. Login theme

- [x] 3.1 Style the social-provider section in `tf/deps/keycloak/theme/freepod/login/resources/css/login.css` to match the Freepod login page while keeping Google's required mark and wording, and verify the login page renders it at desktop and phone width against a local `keycloak:24.0` with a dummy Google provider.
- [x] 3.2 Rebuild and push the image with `./scripts/build-images.sh --keycloak`, restart Keycloak (it pulls `keycloak_image` with `Always`), and verify it comes back healthy with the new stylesheet served.

## 4. Privacy policy

- [x] 4.1 In `legal/privacy-policy.md` §2, add Google as a source of account data (name, email and Google account identifier, when you choose to sign in with Google), bump the effective date, and verify the UI legal-document tests still pass.

- [x] 4.2 Publish each legal document's markdown at `/legal/<slug>.md` (`text/plain; charset=utf-8`), because Google's verification checker fetches the SPA without running it and found `/legal/privacy` empty, and verify all four return 200 on `freepod.eu` while an unknown slug returns 404.

## 5. Rollout and verification

- [x] 5.1 `terraform apply` in `tf/deps/` and verify the realm's login page on both `freepod.eu` and `dev.freepod.eu` shows the Google button.
- [x] 5.2 Sign in with a Google account that has no Freepod account and verify: account created with username = email, `emailVerified` true, no verification email, no profile form, and `/api/me` returns that email.
- [x] 5.3 Sign in with Google using the email of an existing password account and verify the confirm-link page appears, the link happens only after the emailed link or the password, the account's attributes are unchanged, and `/api/me` shows the same user and deployments for both sign-in methods.
- [x] 5.4 Abandon the link at the confirmation page and verify no account is created and no identity is linked (admin console, the user's "Identity provider links").
- [x] 5.5 Try the registration form with the email of the Google-created account from 5.2 and verify it is refused, then verify self-service password reset adds a password to that same account.
- [x] 5.6 Verify `freepod login` (browser and device flow) and one "Sign in with Freepod" app both offer Google and resolve the same account, and that a Google account outside `freepod-dev` is refused on `dev.freepod.eu`.

## 6. Documentation

- [x] 6.1 Note the Google provider, its credential variables and the Google Cloud console location in `tf/deps/README.md`, and verify the README's secrets list matches `variables.tf`.
- [x] 6.2 After archiving, rewrite the Purpose of `openspec/specs/keycloak-user-realm/spec.md`, which says social identity providers are deliberately not part of the realm, so it points at `keycloak-google-identity-provider` instead.
