# Tasks

## 1. Preconditions

- [ ] 1.1 Confirm on dev that Keycloak 24 puts `sid` in the ID tokens it issues to `freepod-apps-dev`, and that the value is stable across silent sign-ins in one browser and differs between browsers. Verify: decode the ID tokens of two silent sign-ins and one sign-in from a second browser, from a throwaway authorization-code flow against `freepod-apps-dev`, and record the result in design D4.

## 2. Data model and grants

- [ ] 2.1 Add `app_auth_sign_in` (primary key `keycloak_sid, deployment_id`, cascade from `deployment`, `subject`, `sid`, `signed_in_at`) and `app_auth_ended_session` (`keycloak_sid` primary key, `ended_at`), plus nullable `app_auth_code.keycloak_sid` and `app_auth_oidc_code.sid`, as ORM models and an Alembic migration. Verify: a migration test upgrades and downgrades cleanly, and deleting a deployment removes its sign-in records.
- [ ] 2.2 Grant `caelus_app_auth` `SELECT, INSERT, UPDATE, DELETE` on `app_auth_sign_in` and `SELECT, INSERT, DELETE` on `app_auth_ended_session` in `tf/app/caelus/app-auth-bootstrap.sql` (D9). Verify: run it twice against the test database; as `caelus_app_auth`, the allowed statements succeed and updating `app_auth_ended_session` is refused.

## 3. Daemon: session IDs through sign-in

- [ ] 3.1 Keep Keycloak's `sid` in `identity` at the exchange and refuse an ID token without one (D4). Verify: `broker_test.go` shows a stub ID token without `sid` yields the error page and no code.
- [ ] 3.2 Carry the Keycloak session ID through the header code record into a `ksid` field of the session cookie. Verify: a test signs in through the broker and the verifier and finds the stub's `sid` in the redeemed session, and a cookie without `ksid` is still accepted.
- [ ] 3.3 Derive the app's `sid` per D3, store it on the OIDC code record, and put it in the ID token. Advertise `backchannel_logout_session_supported: true`. Verify: `provider_test.go` shows equal `sid`s for two sign-ins in one Keycloak session, different ones across clients and across sessions, none equal to Keycloak's, and a stable value after a keyring rotation; `oidc_test.go` checks the discovery flag.

## 4. Daemon: sign-in records and sign-out

- [ ] 4.1 Upsert the sign-in record in the same transaction as the OIDC code (D5), and answer `server_error` when the write fails. Verify: `store_test.go` covers the upsert keeping one row per session and deployment; `provider_test.go` covers the failure path.
- [ ] 4.2 Add `POST /backchannel-logout` per the `app-sign-out` spec and D2 and D6. Verify: tests with a stub Keycloak key for a valid token, a forged signature, the wrong audience, no `sid`, a `nonce`, an `iat` three minutes old, a replay (no second delivery), and a database error (`500`).
- [ ] 4.3 Deliver logout tokens in the background per D7, reading `auth.oidc.backchannelLogoutPath` in `ssoClient`. Verify: against stub apps, the token verifies with `typ: logout+jwt`, `aud`, `sub`, the app's `sid`, the event and no `nonce`; a `500`, a redirect and a timeout are logged and not retried; a deleted deployment, a header deployment and an invalid path receive nothing; the endpoint answers before a slow app does.

## 5. Daemon: verifier

- [ ] 5.1 Add the ended-session cache per D8 and refuse sessions whose `ksid` it holds. Verify: `verify_test.go` with a fake clock and store covers a refusal within 10 seconds, other sessions unaffected, a cookie without `ksid`, an outage keeping the copy, the never-loaded error, the inclusive watermark, and pruning after 7 days.

## 6. Daemon: purge and release

- [ ] 6.1 Extend the purge loop with the D9 deletions, and pin `sessionTTL` to the ended-session retention in a test. Verify: `store_test.go` deletes a 31-day sign-in record and an 8-day ended session and keeps younger ones, and the pinning test fails if either constant changes alone.
- [ ] 6.2 Update `daemons/app-auth/README.md` with the sign-out path as a terse entry with spec links, bump `daemons/VERSION`, and run `go vet` and `go test ./...`. Verify: green, and the README names no removed behavior.

## 7. Keycloak and the dashboard

- [x] 7.1 oauth2-proxy stops requesting `offline_access` and refreshes after one minute (`tf/app/login/main.tf`), applied on dev. Verify: dev's `/oauth2/start` asks for `scope=openid email profile`.
- [x] 7.2 `freepod-dev` issues 60-second access tokens (`tf/deps/keycloak-config/clients.tf`), applied. Verify: the client's `access.token.lifespan` attribute is `60` in Keycloak.
- [ ] 7.3 Add the back-channel settings of D1 to `freepod-apps-dev` and `freepod-apps-prod`, and `access_token_lifespan = "60"` to `freepod-prod`. Apply only the `freepod-apps-dev` change now. Verify: the `tf/deps` plan touches only `freepod-apps-dev` before the apply, and only the two prod clients when the rest is applied in 9.2.

## 8. Docs

- [ ] 8.1 Describe signing out in `ui/docs/developers/authentication.mdx`: a sign-out anywhere signs that browser out of header apps within seconds, and OIDC apps that declare a back-channel logout path receive a logout token with the session's `sid`. Describe the present only. Verify: the docs build.

## 9. Rollout and verification

- [ ] 9.1 Dev: apply the migration and grants, release and roll out the daemon, apply 7.3 for dev, and roll out the API and UI. Verify each:
  - **Carried from `app-access-list`:** on a dev custom app with `"access": "listed"`, the owner gets in; a second account is refused until added, then gets in and receives the invitation; after removal it is refused within 30 seconds with no reconcile. The dev studio admits its owner and refuses a second account until it is added. Immich signs in on the web and the phone; removing a listed person ends both of their sessions; removing someone while Immich is scaled to zero answers `502` and keeps the entry.
  - **Sign-out from the dashboard:** with dev Immich and a header app signed in from one browser, signing out of the dashboard ends the Immich web session and the header session within 10 seconds, while Immich on the phone stays signed in.
  - **Sign-out from Immich:** the header app ends within 10 seconds and the dashboard within a minute. Signing in again needs a password, then is silent for the dashboard.
  - **App down:** with Immich scaled to zero, signing out of the dashboard still completes, and app-auth logs the failed delivery.
  - **Screenshot:** a dev dashboard screenshot of the Access dialog matching canvas boards 2a–2c, carried from `app-access-list`.
- [ ] 9.2 Prod, only with Erik's go-ahead: roll out `app-access-list` and this change, apply the prod halves of 7.3 and the prod `tf/app` (oauth2-proxy), and repeat 9.1's checks on prod's studio and immich-sso. Verify: the prod studio admits only its owner, prod immich-sso signs in, and a dashboard sign-out ends the prod Immich web session.
- [ ] 9.3 After every App Studio deployment on dev and prod serves chart 0.2.19 or later, remove `allowCache` and `a=` from the verifier and its spec references, and release the daemon. Verify: `git grep -n "allowCache\|\"a\"" daemons/app-auth` finds nothing, and `go test ./...` passes.

## Workflow follow-up

- Archive `app-session-logout` after prod is verified, and sync its delta specs.
- Next change: `nextcloud-sso`, a sandbox chart that declares `auth.access: listed` and the `user_oidc` back-channel logout path.
