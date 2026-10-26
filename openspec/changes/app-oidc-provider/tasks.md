# Tasks

## 1. Schema and role (D5)

- [ ] 1.1 Add an Alembic migration in `api/` creating `app_auth_oidc_code` (`code_hash` bytea primary key, `deployment_id` uuid, `redirect_uri`, `subject`, `email`, `name`, `nonce` and `code_challenge` nullable, `expires_at` naive UTC, index on `expires_at`), with its SQLModel in `api/app/models/app_auth.py`. Verify with `uv run --no-sync alembic upgrade head` and `downgrade -1` against the test database.
- [ ] 1.2 Grant `SELECT, INSERT, DELETE` on the table in `tf/app/caelus/app-auth-bootstrap.sql`. Verify by running `store_test.go` as `caelus_app_auth`.

## 2. Provider core (D1, D3, D4, D6)

- [ ] 2.1 Add configuration to `main.go`: `APP_AUTH_OIDC_CLIENT_KEYS` (keyring, as `APP_AUTH_SESSION_KEYS`) and `APP_AUTH_OIDC_SIGNING_KEYS` (PEM RSA keys, current first). Both are optional, and the provider's routes are absent when either is unset, so the image can roll out ahead of Terraform. Verify with `go vet ./...`.
- [ ] 2.2 Add `ssoClient(ctx, deploymentID)` to the store: the eligibility query keyed by ID on `sso.enabled`, returning the hostname and the template's `sso.redirectUris`, with `memstore_test.go` support. Add `store_test.go` cases for user value, template override, unapplied release and deletion. Verify with `go test ./...`.
- [ ] 2.3 Implement client-secret derivation and constant-time verification across the keyring, and redirect URI validation (D4), as pure functions with table tests covering every scenario in the spec's redirect requirement. Verify with `go test ./...`.
- [ ] 2.4 Implement the RS256 signer and the JWKS document with `kid` derived from the public key (RFC 7638 thumbprint), and the sealed access token under purpose `oidc-access`. Verify with tests that round-trip an ID token through `go-oidc`'s verifier against the served JWKS.

## 3. Endpoints (D1, D2, D5, D7, D8, D9)

- [ ] 3.1 Serve `/.well-known/openid-configuration` and `/oidc/jwks`. Verify with a test that `go-oidc`'s `NewProvider` accepts the issuer.
- [ ] 3.2 Serve `/oidc/authorize`: validate the client and redirect URI first (error page, no redirect), then the remaining parameters (errors to the redirect URI), then start the existing Keycloak leg with the flow cookie marked as an OIDC sign-in. Extend `/callback` and `/consent` to finish an OIDC sign-in by storing a code and redirecting to the redirect URI with `code` and `state`. Verify with `broker_test.go`-style tests for the spec's authorization scenarios.
- [ ] 3.3 Serve `POST /oidc/token` (both client authentication methods, redirect URI and PKCE checks, `invalid_client` / `invalid_grant` responses, `Cache-Control: no-store`) and `GET|POST /oidc/userinfo`. Verify with tests for replay, cross-client codes, missing verifier and expired access tokens.
- [ ] 3.4 Serve `/oidc/logout`, reusing the broker's end-session round trip with the validated post-logout redirect carried in the sealed logout state. Verify with tests for return-to-app and foreign redirects.
- [ ] 3.5 Add an end-to-end test that drives a real `golang.org/x/oauth2` + `go-oidc` client through authorize, consent, token and userinfo against the stub identity provider. Verify with `go test ./...`.
- [ ] 3.6 Update `daemons/app-auth/README.md` (a third role: the provider; its keys and their rotation) and bump `daemons/VERSION`. Verify the README's spec links resolve.

## 4. Platform (D10)

- [ ] 4.1 Add `app_auth_oidc_issuer` and `app_auth_oidc_client_keys` to API settings, and an `oidc_client_secret(deployment_id)` helper that derives with the first key in the same format the broker accepts. Add a test pinning one known vector shared with a Go test, so the two implementations cannot drift.
- [ ] 4.2 In the reconciler, for deployments whose merged values enable SSO, publish Secret `<deployment>-oidc` (`OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`) and inject `caelus.oidc.{issuer, clientId, secretName}`, and delete the Secret when SSO is off. Verify with reconciler tests: enabled, disabled, toggled off, template-forced, and no secret in logged values.

## 5. Infrastructure

- [ ] 5.1 In `tf/app/app-auth`, generate the client key (`random_bytes`) and signing key (`tls_private_key`, RSA 2048), and add both to the app-auth Secret. Pass the client keyring and the issuer to the caelus module's API environment. Verify with `terraform plan` in the default (dev) workspace after checking `terraform workspace show`.

## 6. Roll out on dev

- [ ] 6.1 Build and push the daemons image, then apply dev with `-var app_auth_image=…` and the API release. Verify an existing auth-enabled `custom` app still signs in, and App Studio still admits only its owner.
- [ ] 6.2 From a pod in a tenant namespace, `curl https://login.dev.freepod.eu/.well-known/openid-configuration` and the JWKS. Verify they answer. If the hairpin fails, stop and decide the egress fallback (design, Risks) before going on.
- [ ] 6.3 Create a throwaway non-catalog product on dev through `caelus` with `admin` visibility and a minimal chart running an OIDC test client, with `sso.enabled: true`. Sign in with a dev account. Verify the consent page, the ID token's claims and audience, userinfo, logout back to the app, and that a second deployment's credentials are refused.
- [ ] 6.4 Delete the throwaway deployment and product.

## Workflow follow-up

- Bump the `app_auth_image` default in `tf/app/variables.tf` and apply prod once dev is verified.
- Update the Sign in with Freepod paragraph in `AGENTS.md` to point at the new specs.
- Archive the change and sync its specs.
- Next changes: the `immich-sso` sandbox product (app decides), then the
  allowlist and `nextcloud-sso` (people I list).
