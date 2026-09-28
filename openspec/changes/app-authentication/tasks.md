## 1. Identity provider

- [x] 1.1 Declare `freepod-apps-prod` and `freepod-apps-dev` in `tf/deps/keycloak-config/clients.tf` per the keycloak-terraform-config delta: confidential, standard flow and PKCE S256 only, one redirect URI each on the login host, consent not required. Surface both secrets through outputs. Verify with `terraform plan` in `tf/deps` showing exactly two new clients and no other change.
- [x] 1.2 Add workspace-keyed `app_auth_client_id` / `app_auth_client_secret` maps to `tf/app` variables, matching the existing oauth2-proxy credentials. Verify that `terraform plan` in both workspaces resolves the matching client.

## 2. Data model

- [x] 2.1 Add `app_auth_consent` and `app_auth_code` models and an Alembic migration (D8). Verify `alembic upgrade head` and `downgrade -1` round-trip on the test Postgres, and that a test asserts the `(subject, deployment_id)` primary key rejects a duplicate.
- [x] 2.2 Write `tf/app/caelus/app-auth-bootstrap.sql` and the role Terraform, modeled on `ssh-resolver-role.tf`. The role `caelus_app_auth` gets column-level `SELECT` on the eligibility query's columns and `SELECT, INSERT, DELETE` on the two tables. Verify on dev that the role can read `hostname` but gets `permission denied` for `UPDATE deployment` and for reading the encrypted var columns, and that re-running the script is a no-op.

## 3. `app-auth` service: verifier

- [x] 3.1 Scaffold `app-auth/` (Go module, Dockerfile, two listeners, config from env, health endpoints). Wire it into `scripts/build-images.sh` and CI next to `ssh-auth`. Verify `go test ./...` runs in CI and the image builds.
- [x] 3.2 Implement the session cookie (D4): HMAC-SHA256 keyring with key IDs, claims `{sub,email,name,host,iat,exp}`, and a 7-day maximum (first shipped as 12 hours; see D4). Verify with unit tests for: valid, expired, tampered, wrong host, and rotated-key acceptance.
- [x] 3.3 Implement `/verify` for regular paths: cookie filtering across multiple `Cookie` lines (D5); identity headers, with the name percent-encoded; public-path matching on the path only, using cached RE2 patterns decoded from the `p` query parameter and failing closed on bad patterns (D6); navigation detection → 302 with absolute `https://` Location and the login-nonce cookie; 401 otherwise. Verify with table-driven tests covering every scenario in the verifier spec's header, cookie, session, public-path and unauthenticated requirements.
- [x] 3.4 Implement the reserved paths `/.freepod/auth/login`, `/callback`, `/logout` and 404 for the rest (D7). Include return-target sanitization and atomic code redemption bound to host and nonce. Verify with tests for: open-redirect inputs, a replayed code, a code for another host, login CSRF (no matching nonce cookie), and logout clearing only the session cookie.
- [x] 3.5 Run an integration test of the verifier behind a real Traefik (the binary or container, as in the design's context checks). The config should match what the chart renders. Assert that the app receives filtered cookies and identity headers, that spoofed headers never arrive, and that 302s and `Set-Cookie`s reach the client. Verify the test runs in CI.

## 4. `app-auth` service: broker

- [x] 4.1 Implement the OIDC client against Keycloak: authorization code with PKCE S256, `state`/`nonce`, ID token validation, refusal when `email_verified` is false, no token persistence. Verify with tests against a stub OIDC provider for the success, unverified-email and bad-state paths.
- [x] 4.2 Implement host eligibility (a `custom` deployment that isn't deleted, with `auth.enabled`, matched case-insensitively on hostname), checked at `/start` and again before minting the code. Verify with tests covering: custom domain, auth disabled, unknown host, and auth disabled mid-flow.
- [x] 4.3 Implement the consent page and CSRF-protected submission, with idempotent recording and decline. Verify with tests showing that first visit prompts, a return visit skips, decline records nothing, and a recreated deployment prompts again.
- [x] 4.4 Implement code minting (≥128-bit random, stored hashed, 60-second TTL, bound to host, user, return target and nonce), the redirect to `https://<host>/.freepod/auth/callback`, and the periodic expired-code purge. Verify with tests for expiry at 61 seconds, the purge removing codes more than an hour past expiry, and the stored hash not being redeemable.

## 5. Platform deployment

- [x] 5.1 Terraform the `app-auth` Deployment (two replicas, PDB), in-cluster Service, session-key Secret, database credential, and the login-host IngressRoute exposing only the broker listener, in the `login` / `login-dev` namespaces. Verify on dev that `https://login.dev.freepod.eu/healthz` answers, and that the verifier port is unreachable from outside the cluster.
- [x] 5.2 Add `app_auth_verify_url` to API settings. Make the reconciler inject `caelus.appAuth.verifyUrl` for `custom` deployments. Verify with a reconcile unit test asserting the injected values.

## 6. `custom` chart and catalog

- [x] 6.1 Add the strip `Middleware` (a Traefik `headers` middleware removing the seven identity headers), attached to the Ingress on every render. Verify with a chart render test asserting that both annotation and middleware are present when `auth` is absent.
- [x] 6.2 Add the forward-auth `Middleware`, rendered when `auth.enabled`:
  - address `verifyUrl?p=<base64url(JSON public)>`;
  - `authResponseHeaders` listing `Cookie` plus the seven identity headers;
  - `trustForwardHeader` unset, with a comment explaining why;
  - chained after the strip middleware;
  - `required` failure when `verifyUrl` is missing.

  Verify with chart render tests for: enabled, enabled with public patterns, and a missing `verifyUrl` failing.
- [x] 6.3 Bump the chart version. Extend `products/catalog/custom.yaml` `values_schema` with the closed `auth` object (`enabled`, `public` ≤32 × ≤256 chars). Verify with catalog reconciliation tests, and that a deployment with an unknown `auth` key is rejected by schema validation.
- [x] 6.4 Give `auth.enabled` and `auth.public` their own `title` and `description` in the catalog schema: the deploy form labels leaf fields and ignores a parent's title. Verify the dev catalog serves both titles.

## 7. Client and docs

- [x] 7.1 Validate `user_values.auth.public` patterns in the `freepod` CLI before deploy, with a clear error for patterns outside RE2 syntax such as lookarounds and backreferences. Verify with CLI unit tests.
- [x] 7.2 Document authentication in `cli/src/freepod/assets/SKILL.md`: how to opt in, public paths, the header contract (`X-Freepod-User` as the stable key, email may change), `/.freepod/auth/login` and `/logout`, 401 for background requests, and simulating the headers locally. Verify by reading it against the specs.
- [x] 7.3 Add an architecture note for app authentication to `AGENTS.md`, and a README for `app-auth/` stating its coupling to the chart's middleware contract and the platform schema, mirroring `ssh-auth/README.md`. Verify that the links resolve.
- [x] 7.4 Update the privacy policy (and DPA where relevant) under `legal/`: disclosure of name, email and account identifier to operators of apps a user signs in to, on the basis of per-app consent. Bump the document version per `legal-doc-versioning`. Verify that the rendered legal page shows the new version.
- [x] 7.5 Render `type: array` of strings in the deploy form as a multi-line field, one entry per line, submitted as a list with blank lines dropped. Verify with form tests for labels, prefill, blank-line editing and schema validation.
- [x] 7.6 Bump the `freepod` CLI to 0.16.0 for the public-pattern check. Verify `freepod --version`; publishing is the `freepod-v0.16.0` tag after merge.

## 8. Rollout and verification

- [ ] 8.1 Roll out to dev and enable `auth` on a dev copy of milk. Verify end to end in a browser:
  - first sign-in shows consent;
  - the app sees the headers and never the session cookie;
  - public paths are anonymous;
  - logout works;
  - the cookie is rejected on a second app of the same owner.
- [x] 8.2 On dev, probe spoofing: send identity headers to an auth-enabled app and to one that isn't, both through the edge. Verify that neither app receives them, and record the results in the change.
- [ ] 8.3 Have `app-auth` reviewed by someone outside this change (verifier, broker and the chart's middleware contract) and address findings. Verify the review notes are recorded in the change.
- [ ] 8.4 Roll out to prod and enable on milk. Verify sign-in with an existing Freepod account and with a newly registered one.
