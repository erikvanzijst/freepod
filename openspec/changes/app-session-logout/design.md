# Design

## Context

See proposal.md for why. The facts this design rests on:

- **Keycloak has one client for every app sign-in.** app-auth's `freepod-apps-*` client is the only party that signs users in to apps, so a Keycloak SSO session that signed in to any app has a client session for it. Keycloak's back-channel logout reaches exactly the clients with a client session in the ended user session. It sends once, during the logout request, with no retry, and never fails the logout. It sends nothing when a session expires, when Keycloak restarts (Keycloak 24 keeps SSO sessions in memory), or when an admin disables a user.
- **Keycloak's session ID is per browser.** Its ID tokens carry `sid`, and its logout tokens carry the same value when the client requires it. The dashboard's sign-out ends only the current browser's SSO session, through oauth2-proxy's `backend-logout-url`; an app's sign-out does the same through `/oidc/logout`.
- **app-auth already keeps short-lived state and purges it.** It reads and writes `app_auth_consent`, `app_auth_code` and `app_auth_oidc_code`, holds `DELETE` on all three, and runs a 10-minute `purgeLoop` that deletes expired codes from every replica (`main.go`). Header-app sessions are sealed cookies (`verify.go`, `session`) and are not stored.
- **The sign-in path already carries identity through sealed and stored hops.** Keycloak's ID token is reduced to an `identity` at the exchange (`broker.go`), sealed into the pending-consent cookie, written to a code record, and redeemed into a session cookie (header) or an ID token (OIDC, `signer.go`).
- **Immich 3.3.5 is session-aware.** At sign-in it stores the ID token's `sid` as the session's `oauthSid` (`oauth.repository.ts` `getProfileAndOAuthSid`, `auth.service.ts`). Its back-channel endpoint deletes the sessions matching both `sid` and `sub` when the token has a `sid`, and every session of `sub` otherwise (`session.repository.ts` `invalidateOAuth`). It rejects tokens older than two minutes and tokens with a `nonce`. The phone app signs in through the same server callback, so it gets its own session and `sid`.
- **The API already sends sub-only logout tokens** when someone is removed from an access list (`api/app/services/app_access.py`), signed with the provider's key. The daemon has the same key and already validates callback paths with `redirectURIFor` (`client.go`), which the API mirrors.
- **app-auth reaches tenant hosts on their public addresses**, as the API does for its logout tokens. There is no NetworkPolicy in the `login` namespaces, and Keycloak reaches the `app-auth` Service (`8081`, the broker port) in-cluster.

## Goals / Non-Goals

**Goals:**

- Ending a browser's SSO session ends that browser's sessions in every app, within seconds for header apps and with one delivery attempt for OIDC apps.
- No change to how fast or how reliably anyone can sign in, beyond refusing an ID token without `sid`.
- State bounded by the session lifetimes it serves, purged by app-auth alone.

**Non-Goals:**

- Signing out other browsers of the same user. Keycloak's account console already offers "sign out all devices", which ends each session and so reaches this path once per session.
- Retrying deliveries, or a queue that survives a restart.
- Reacting to session expiry, Keycloak restarts or disabled accounts.
- Front-channel logout or session-check iframes: app hosts are on another site than Keycloak, so browsers block the cookies they need.
- Notifying the dashboard. oauth2-proxy cannot receive back-channel logouts; it follows the SSO session through its one-minute refresh instead.

## Decisions

### D1. Keycloak posts to the broker inside the cluster

Each `freepod-apps-*` client gets `backchannel_logout_url = http://app-auth.<namespace>.svc.cluster.local:8081/backchannel-logout`, `backchannel_logout_session_required = true` and `backchannel_logout_revoke_offline_sessions = false`. The handler lives on the broker's mux, so it is also reachable as `https://login.<domain>/backchannel-logout`; that is harmless, because only Keycloak can sign an acceptable token.

Alternative: the public URL. Rejected because it hairpins through the edge for no benefit.

### D2. Verifying Keycloak's logout token

app-auth verifies with the go-oidc verifier it already builds for Keycloak's ID tokens: signature against Keycloak's JWKS, issuer, and audience (its own client ID). It skips go-oidc's expiry check, because logout tokens need not carry `exp`, and enforces `iat` within two minutes (with five seconds of skew) itself. It then requires the back-channel logout event, a non-empty `sid`, and no `nonce`, so an ID token can never pass as a logout token.

### D3. The `sid` given to an app

`sid = base64url(HMAC-SHA256(k, client_id ‖ 0x00 ‖ keycloak_sid))`, where `k` is derived from the first key of app-auth's sealing keyring under a dedicated purpose label. The value is computed once, when the provider issues a code, and stored in both the OIDC code record and the sign-in record, so rotating the keyring never changes a `sid` already issued.

Alternatives:
- Keycloak's own `sid`. Rejected: apps would learn the identity provider's session ID, and two tenants' apps could tie their sessions to one browser.
- A random `sid` per sign-in. Rejected: signing in to the same app twice in one browser would yield two `sid`s, while the sign-in record keeps one per session and deployment, so the first app session would survive the sign-out.

### D4. Carrying the Keycloak session ID

- The exchange keeps `sid` in `identity` and refuses an ID token without one (fail closed: a sign-in nothing could sign out). Keycloak 24 includes `sid` in every ID token; task 1.1 confirms it on dev.
- Pending consent already seals the whole `identity`, so it carries `sid` unchanged.
- Header apps: `app_auth_code` gains `keycloak_sid`, and the session cookie gains a `ksid` field. Cookies issued before this change have none and stay valid until they expire.
- OIDC apps: `app_auth_oidc_code` gains `sid` (the app's value, D3). The ID token issued at redemption carries it.

### D5. Recording OIDC sign-ins at code issue

When `issueOIDCCode` issues a code, it inserts the code record and upserts the sign-in record (`keycloak_sid`, `deployment_id`, `subject`, `sid`, `signed_in_at`) in one transaction. The primary key is (`keycloak_sid`, `deployment_id`), with a cascade from `deployment`. A failed write issues no code.

Recording at issue rather than at redemption keeps the write where app-auth already writes. A code that is never redeemed leaves a record whose logout reaches an app with no matching session, which Immich answers with `200`.

Header apps need no record: their cookie carries the Keycloak session ID, and the verifier checks it (D7).

### D6. The logout endpoint

`POST /backchannel-logout`, in one transaction:

1. `INSERT INTO app_auth_ended_session (keycloak_sid, ended_at) VALUES ($1, now()) ON CONFLICT DO NOTHING`.
2. `DELETE FROM app_auth_sign_in WHERE keycloak_sid = $1 RETURNING deployment_id, subject, sid`.

It commits, answers `200`, and hands the deleted rows to a goroutine. A replayed logout finds no rows, so it sends nothing. A database error answers `500`, which Keycloak only logs.

Deleting before delivery matches "no retry": a pod that dies mid-delivery loses the remaining tokens, as an app that is down would.

### D7. Background delivery

For each row, the goroutine:

1. looks the deployment up through `ssoClient`, which now reads `auth.oidc.backchannelLogoutPath`;
2. skips the row unless the deployment is still an OIDC client with a valid path (`redirectURIFor`);
3. signs a logout token as the API does, with `sid` added;
4. POSTs it with a 10-second timeout and no redirects, and logs the deployment and the status.

Rows are delivered concurrently, at most eight at a time per ended session.

The token format is shared with the API's revocation token. Both sides pin it with tests: the API's never carries `sid`, the daemon's always does.

### D8. The verifier's ended-session cache

The verifier keeps a set of ended Keycloak session IDs:

- **First load:** every row, which the purge bounds to 7 days.
- **Refresh:** every 5 seconds, reading rows with `ended_at` at or after the latest it has seen. The comparison is inclusive and the set deduplicates, so rows committed with the same timestamp are not missed.
- **On database errors:** it keeps its copy.
- **Before the first successful load:** it answers signed-in requests with an error, as it does when the verifier is down.
- **Pruning:** entries older than 7 days are dropped.

A session cookie whose `ksid` is in the set counts as no session, so the browser goes back through sign-in, which Keycloak, without an SSO session, answers with its login page.

Alternatives:
- A per-request query. Rejected: the verifier's per-request path stays off the database.
- A per-host cache like the access list's. Rejected: ended sessions are not per host.

### D9. Purging

`purgeLoop` gains two deletions:
- sign-in records whose `signed_in_at` is older than 720 hours, `sso_session_max_lifespan` in `tf/deps/keycloak-config/realm.tf`;
- ended sessions older than 168 hours, `sessionTTL` in `verify.go`.

Both constants name their source in a comment. A test pins `sessionTTL` to the ended-session retention, so changing one without the other fails. Both deletions run on every replica, as the code purge does.

The grants are `SELECT, INSERT, UPDATE, DELETE` on `app_auth_sign_in` (`UPDATE` for the upsert) and `SELECT, INSERT, DELETE` on `app_auth_ended_session`.

### D10. The dashboard

These were already applied on dev in this branch:
- oauth2-proxy drops `offline_access` and refreshes after one minute (`tf/app/login/main.tf`);
- `freepod-dev` issues 60-second access tokens.

A failed refresh keeps oauth2-proxy's session only until its access token expires (oauth2-proxy 7.14.2, `stored_session.go`), so the token's lifespan is what bounds the dashboard after a sign-out elsewhere. Prod gets `access_token_lifespan = "60"` on `freepod-prod`.

## Risks / Trade-offs

- **[Keycloak never retries]** If app-auth is down when a session ends, nothing is recorded, and the browser's app sessions continue. → Accepted. The sign-in records age out in 30 days.
- **[SSO sessions vanish on a Keycloak restart without a logout]** App sessions from those SSO sessions continue until they expire. → Accepted for now; persistent sessions come with a Keycloak upgrade.
- **[Sessions issued before the rollout]** Header cookies without `ksid`, and Immich sessions without `oauthSid`, cannot be ended by a sign-out. → They expire, within 7 days for header apps and on Immich's own schedule. Revocation from the access list still ends Immich sessions, because it sends no `sid`.
- **[A user's sign-out waits on app-auth]** Keycloak posts during the user's logout request. → The endpoint runs two statements and contacts no app before answering.
- **[A slow app]** Each delivery is capped at 10 seconds and runs in the background, eight at a time.
- **[The endpoint is public]** Anyone can post to it. → Unsigned or misaddressed tokens are refused before any database write.
- **[A sign-in without `sid`]** Refusing it turns a Keycloak configuration change into failed sign-ins. → Task 1.1 confirms Keycloak sends `sid`, and the broker logs every refusal.
- **[The dashboard refreshes every minute]** That is one refresh per active dashboard user per minute against Keycloak. → Small at current scale.

## Migration Plan

1. Migration (new tables, nullable columns) and bootstrap grants, then the daemon release. The daemon tolerates code records without the new columns, so in-flight sign-ins survive the rollout.
2. Keycloak back-channel settings on the `freepod-apps-*` client of the environment being rolled out. Until the daemon has the endpoint, Keycloak's posts get a `404`, which it only logs.
3. Prod, together with `app-access-list`: run that change's rollout, then this one's, then `freepod-prod`'s token lifespan and the prod `tf/app` apply (oauth2-proxy), then remove `a=` and `allowCache`.

Rollback: redeploy the previous daemon. It ignores the new columns and tables, and Keycloak's posts fail harmlessly. The oauth2-proxy change rolls back by restoring the scope and refresh interval.
