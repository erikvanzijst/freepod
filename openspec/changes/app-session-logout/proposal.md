# Proposal

## Why

Sign in with Freepod should make the dashboard and its apps feel like one product, but their sessions live separately. Signing out of the dashboard leaves the user signed in to every app. Signing out of an app left the dashboard signed in indefinitely, because the dashboard rode an offline session, so the next app sign-in asked for a password the dashboard never needed. A browser can end up signed in as one account on the dashboard and another in an app. This change ties the dashboard to Keycloak's SSO session and carries every sign-out, wherever it starts, to the apps that browser signed in to.

It also carries what remains of `app-access-list`: its verification on dev and its prod rollout, which ship together with this change, and the removal of the verifier's legacy allowed-accounts parameter once prod serves the new charts.

## What Changes

- **The dashboard follows the SSO session.** oauth2-proxy stops requesting `offline_access`, refreshes every minute, and its Keycloak clients issue one-minute access tokens. While the dashboard is signed in, app sign-ins need no password. Once the SSO session ends, the dashboard signs out within a minute. Done on dev; prod is open.
- **Keycloak notifies app-auth when an SSO session ends.** The app-authentication clients get an in-cluster back-channel logout URL that requires the session ID (`sid`).
- **app-auth ties each app session to the Keycloak session it came from:**
  - header-app sessions carry the Keycloak `sid`;
  - OIDC apps receive a `sid` in their ID tokens, a keyed hash of the Keycloak `sid` and the client ID, and discovery advertises `backchannel_logout_session_supported: true`;
  - each OIDC sign-in is recorded with both `sid`s, so a sign-out can find it.
- **A sign-out ends that browser's app sessions:**
  - app-auth records the ended Keycloak session and answers Keycloak at once;
  - the verifier refuses header-app sessions from an ended Keycloak session within seconds;
  - each OIDC app the browser signed in to receives a logout token carrying its `sid`, sent in the background; a failure is logged and never retried, and never fails the sign-out.
- **Bounded state:** app-auth purges sign-in records after 30 days and ended sessions after 7 days, the realm's SSO session cap and the header session lifetime.
- Removing someone from an access list is unchanged: its logout token carries no `sid`, so it ends all of that person's sessions in the app.
- Carried from `app-access-list`: the dev verification, the prod rollout of both changes, and removing `allowCache` and `a=` from the verifier.

## Capabilities

### New Capabilities

- `app-sign-out`: how ending a Keycloak SSO session ends the app sessions that browser started through Sign in with Freepod: the back-channel endpoint, the sign-in records, propagation to OIDC apps, refusing header-app sessions, and how long the records are kept.

### Modified Capabilities

- `app-auth-verifier`: a session is also invalid once the Keycloak session it came from has ended.
- `app-auth-broker`: the broker keeps the Keycloak session ID from the identity provider's ID token and carries it into the app session.
- `app-oidc-provider`: ID tokens carry a per-client `sid`; discovery advertises session-aware back-channel logout; logout tokens carry a `sid` when they end one session; tokens for a sign-out are sent without failing it.
- `app-auth-data-model`: sign-in code records carry the Keycloak session ID and OIDC code records the app's `sid`; new sign-in and ended-session records; the app authentication role may delete from those two tables.
- `keycloak-terraform-config`: the app-authentication clients declare a back-channel logout URL and require the session ID.
- `keycloak-user-realm`: the dashboard clients issue one-minute access tokens.
- `oauth2-proxy-deployment`: the dashboard session is tied to the SSO session and refreshes every minute.

## Impact

- **app-auth daemon** (`daemons/app-auth/`): the Keycloak exchange keeps `sid`; the session cookie, both code records and ID tokens carry session IDs; a new `POST /backchannel-logout` endpoint on the broker port; background logout delivery; the verifier's ended-session cache; the purge loop's two new deletions. Released as a new daemons version.
- **Database**: new tables `app_auth_sign_in` and `app_auth_ended_session`, a `keycloak_sid` column on `app_auth_code` and a `sid` column on `app_auth_oidc_code`, and the role's grants on the new tables (`tf/app/caelus/app-auth-bootstrap.sql`). The migration lives in `api/alembic`.
- **Keycloak** (`tf/deps/keycloak-config`): the `freepod-apps-*` clients' back-channel settings, and one-minute access tokens on `freepod-prod`, matching `freepod-dev`. This is the shared Keycloak instance, so its prod half is applied with the prod rollout.
- **oauth2-proxy** (`tf/app/login`): already changed and applied on dev; prod takes it at the prod apply.
- **Apps**: Immich 3.3.5 already stores the ID token's `sid` and ends only that session on a logout token carrying it. Header apps need no change.
- **Not covered**: sessions that expire, SSO sessions lost when Keycloak restarts, other browsers of the same user, and apps that are down when a sign-out is delivered.
