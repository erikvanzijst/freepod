# Tasks

## 1. Data model and grants

- [ ] 1.1 Add `AppAccessEntryORM`, `AppAccessLogoutORM` and `AppAccessInvitationORM` to `api/app/models/app_auth.py` and an Alembic migration for `app_access_entry`, `app_access_logout` and `app_access_invitation` with the constraints in design D4 (lower-case check, unique `(deployment_id, email)`, partial unique `(deployment_id, subject)`, cascades). Verify: a migration test, like `test_migration_app_auth.py`, upgrades and downgrades cleanly and the duplicate-email and duplicate-subject inserts fail.
- [ ] 1.2 Extend `tf/app/caelus/app-auth-bootstrap.sql` with the D4 grants (`deployment.user_id`, `"user"(id, email)`, `SELECT` plus `UPDATE (subject, name, bound_at)` on entries, `SELECT, UPDATE, DELETE` on the outbox, nothing on invitations). Verify: run it twice against the test database; as `caelus_app_auth`, inserting an entry, changing its email and reading `"user".name` are refused, and the allowed statements succeed.

## 2. Daemon: the `auth` contract

- [ ] 2.1 Rewrite `eligible` and `ssoClient` in `daemons/app-auth/store.go` to return effective `enabled`, `protocol` and `access` per D2. Header eligibility requires `protocol = header`, the provider requires `protocol = oidc` and reads `auth.oidc.{redirectPaths,nativeRedirectUris,pkce,backchannelLogoutPath}` from system values only. An unknown protocol is ineligible, and an unknown access is `listed`. Verify: `store_test.go` cases for each default, user-over-system precedence, OIDC on the header path, header on the OIDC path, and `auth.oidc` in user values being ignored.
- [ ] 2.2 Validate `backchannelLogoutPath` with the callback-path rules in `client.go`. Verify: `client_test.go` reuses the userinfo, suffix and port tricks for the logout path.
- [ ] 2.3 Remove every `sso.*` read from the daemon and its README. Verify: `git grep -n "sso\." daemons/app-auth` finds only prose about the old name, if anything.

## 3. Daemon: admission and binding

- [ ] 3.1 Add the D3 admission function with store queries for the owner email and the entries, and the conditional bind `UPDATE`, plus `memstore_test.go` support. Verify: unit tests for owner (case-insensitive), bound subject, unbound email, an email bound to another subject, and two concurrent binds by the same subject.
- [ ] 3.2 Apply it in the header broker after the IdP callback and before consent, and again where the code is issued (binding there). Refusals render the no-access page on the login host. Verify: `broker_test.go` shows a stranger on a `listed` host sees no consent page and gets no code, the owner with an empty list gets a code, and a first sign-in binds the entry.
- [ ] 3.3 Apply it in the provider at the callback, before consent, and on the consent POST (binding there), with `access_denied` for `prompt=none`, and again at the token endpoint (`invalid_grant`) and userinfo (`401 invalid_token`). Verify: `provider_test.go` covers each refusal point, including an entry removed between code and token.
- [ ] 3.4 Update the no-access page wording per the verifier spec, on both hosts. Verify: a page test asserts the app name, address, email and "ask whoever shared the link" text.

## 4. Daemon: verifier

- [ ] 4.1 Add the D7 access cache (per deployment, 30-second refresh, reload before refusing if older than 5 seconds, stale on error, refuse when never loaded, bounded size) and handle `l=1`, with any other `l` value refusing signed-in requests. Resolve preview hostnames as the broker does. Verify: `verify_test.go` with a fake clock and store covers owner, listed, stranger, public path, anonymous public, preview alias, removal after 30 seconds, addition with refresh-on-refuse, outage with and without a copy, and a bad `l`.
- [ ] 4.2 Keep `a=` working alongside `l=1` until task 7.6. Verify: the existing `a=` tests still pass.

## 5. Daemon: back-channel logout

- [ ] 5.1 Sign logout tokens per D9 and advertise `backchannel_logout_supported: true` and `backchannel_logout_session_supported: false` in discovery. Verify: `oidc_test.go` checks the token verifies against JWKS with `typ: logout+jwt`, `aud`, `sub`, the event and `exp - iat == 120`, and has no `nonce` or `sid`.
- [ ] 5.2 Add the D8 outbox worker (5-second poll, `FOR UPDATE SKIP LOCKED`, client re-check, fresh token per attempt, no redirects, 2xx deletes, 400 deletes and logs, otherwise backoff until 60 minutes). Verify: `e2e_test.go` with an `httptest` RP covers delivery, a 503 then success, a 400, a client that stopped being `oidc`, and expiry after an hour on a fake clock.

## 6. API

- [ ] 6.1 Replace `app_auth_oidc.sso_enabled` with a helper returning the effective `auth` settings (D2) and use it in `reconcile.py`, where OIDC credentials go only to `enabled` with `oidc`. Verify: `test_app_auth_oidc.py` and `test_reconcile_oidc.py` updated to `auth.*`, including header deployments getting no OIDC Secret.
- [ ] 6.2 Add the `auth` summary (`enabled`, `protocol`, `access`, `listed_count`) to `DeploymentRead` from the applied release, with one grouped count query on list endpoints. Verify: API tests for defaults, a `listed` deployment with three entries, no applied release, and a query-count assertion on the listing.
- [ ] 6.3 Add `GET`, `POST` and `DELETE` under `/users/{user_id}/deployments/{deployment_id}/access` per D5, with owner-only writes, administrator reads, the row lock, the outbox insert for bound OIDC removals, and the status codes. Verify: API tests for each status code, an administrator write refused, 500 concurrent additions never exceeding the bound, and removal of a bound entry on an `oidc` deployment writing exactly one outbox row in the same transaction.
- [ ] 6.4 Send invitations per D6 (fixed text, background task after commit, daily limit setting, a seven-day sweep of invitation records). Verify: tests with a stubbed mailer for the message text, a relay failure keeping the entry, `429` at 101, add-and-remove not resetting the count, and the sweep.
- [ ] 6.5 Run the full `api/` suite with `-n 8`. Verify: green.

## 7. Charts and catalog

- [ ] 7.1 `custom` chart: add `auth.access` to `values.schema.json` and the catalog template's user schema, render forward-auth only for `header`, and append `l=1` when `listed`. Bump the chart version. Verify: `test_custom_chart.py` covers `listed` rendering `l=1` and no account, `anyone` rendering no `l`, and `protocol`/`oidc` refused by the schema.
- [ ] 7.2 `immich-sso` chart 0.1.2: read `auth.enabled` and `auth.protocol` instead of `sso.*`. Write the new template version's system values per the `immich-sso` delta, including `/api/oauth/backchannel-logout`, and update its README. Verify: `test_immich_sso_chart.py` updated; `git grep -n "sso\." products/immich-sso` finds nothing.
- [ ] 7.3 App Studio chart: require `enabled`, `header` and `listed`; drop `$owner`, `$allowed` and `a=`; add `l=1`. Set `auth.access: listed` in `products/catalog/appstudio/appstudio.yaml` and bump the chart version. Verify: `test_appstudio_chart.py` covers rendering failing for `anyone` and without the verifier address, and the middleware carrying `l=1`, `n=` and no account.
- [ ] 7.4 Catalog validation: fail a template whose system values enable `auth` without `auth.access`. Verify: a `test_catalog_format.py` case, and the shipped catalog passes.
- [ ] 7.5 Publish the chart versions (never overwrite an existing version) and update `products/catalog` releases. Verify: `scripts/publish-charts.sh --skip-if-published` publishes only the new versions.
- [ ] 7.6 After every App Studio deployment on dev and prod serves the new chart, remove `allowCache` and `a=` from the verifier and its spec references, and release the daemon. Verify: `git grep -n "allowCache\|\"a\"" daemons/app-auth` finds nothing, and `go test ./...` passes.

## 8. UI

- [ ] 8.1 Add the `auth` summary to the API types. In `DeploymentRow`, add the Access button for `listed`, the "Who can sign in" fact ("You and N people", "Only you", or "Managed in {appName}"), and the collapsed-row summary. Verify: `DeploymentRow.test.tsx` covers listed, anyone, not enabled and any product.
- [ ] 8.2 Add the `AccessDialog` component (owner row, entries with bound and unbound states, the add form with mapped errors, confirm-in-row removal, search and filters past 10 entries, the count of places used, scrolling list). Verify: component tests for each state, and a screenshot on the dev UI matching canvas boards 2a–2c.
- [ ] 8.3 Add a read-only `AccessPanel` to the admin `DeploymentDialog`. Verify: a component test showing entries and no controls.
- [ ] 8.4 Run `npm test` and `npm run lint` in `ui/`. Verify: green.

## 9. Docs

- [ ] 9.1 Document `auth.access` in `ui/docs/developers/authentication.mdx`, `cli/README.md` and the `deploy-to-freepod` skill (`cli/src/freepod/assets/SKILL.md`), describing the present behavior only. Verify: the docs build, and the example `.freepod.json` validates against the custom schema.
- [ ] 9.2 Update `daemons/app-auth/README.md` and `products/immich-sso/README.md` for `auth.*`, the access list and back-channel logout, as terse entries with spec links. Verify: no `sso.` keys remain in either.

## 10. Rollout and verification on dev

- [ ] 10.1 Apply the migration and bootstrap grants on dev, then roll out the daemon (task groups 2–5), then immich-sso 0.1.2 and its template, and upgrade the dev sandbox deployment. Verify: sign in to dev immich-sso on the web and the phone works as before.
- [ ] 10.2 Roll out the API and UI on dev. Verify: on a dev custom app with `"access": "listed"`, the owner gets in. A second account is refused with the no-access page until it is added. After being added it gets in and receives the invitation email. After removal it is refused within 30 seconds, with no reconcile in the deployment's history.
- [ ] 10.3 Roll out the App Studio chart on dev and upgrade the dev studio. Verify: the owner gets in, a second account is refused, and after adding it, it gets in.
- [ ] 10.4 Exercise back-channel logout against a real app on dev: an admin-only template version of immich-sso with `auth.access: listed`, whose listed user also exists in Immich. Verify: removing them ends their Immich web and phone sessions within a minute, and the outbox row is gone.
- [ ] 10.5 Repeat 10.1–10.3 on prod, then do 7.6. Verify: the prod studio admits only its owner, and prod immich-sso signs in.

## Workflow follow-up

- Archive `app-access-list` and sync its delta specs.
- Next change: `nextcloud-sso`, a sandbox chart that declares `auth.access: listed` and the `user_oidc` back-channel logout path.
