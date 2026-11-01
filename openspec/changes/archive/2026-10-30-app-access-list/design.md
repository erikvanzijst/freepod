# Design

## Context

See proposal.md for why. The facts this design rests on:

- **The platform already decides from the serving release.** The broker's `eligible` and `ssoClient` queries (`daemons/app-auth/store.go`) read each `auth`/`sso` key as the release's user value over the template's system value. The reconciler merges the same way (`app_auth_oidc.sso_enabled`, `template_values.merge_values_scoped`). Every new key follows that pattern.
- **The verifier is one process with the broker and the provider.** They share a Postgres pool (`main.go`), and the verifier's session already carries `Sub`, `Email` and `Name` (`verify.go`). Today the verifier touches the database only to redeem codes. Per-request decisions come from the middleware URL (`p=` public paths, `a=` allowed emails, `n=` app name).
- **`a=` is used by App Studio alone**, built from the reconciler-injected `caelus.owner.email` (`products/appstudio/chart/templates/app-auth.yaml`). `caelus.owner` itself stays: Docmost, BookStack, Discourse, immich-sso and the App Studio statefulset use it for other things.
- **The app authentication role is narrow.** It reads column-granted deployment, release and template fields and writes only its own tables (`tf/app/caelus/app-auth-bootstrap.sql`). It cannot see who owns a deployment.
- **Both target apps accept a `sub`-only logout token:**
  - Nextcloud `user_oidc` ends every session for `sub` and `iss` when the token has no `sid` (`lib/Controller/LoginController.php`, `backChannelLogout`), at `POST /apps/user_oidc/backchannel-logout/{provider}`.
  - Immich deletes every session of the user whose `oauthId` is `sub` (`session.repository.ts`, `invalidateOAuth`), at `POST /api/oauth/backchannel-logout`. It verifies the token with `maxTokenAge: '2m'` and rejects a `nonce`.
  - So the provider needs no record of sessions or `sid`s.
- **Keycloak enforces unique, verified emails, and email is the username.** At any moment one account holds a given verified email. Over time it can pass to someone else: an account is deleted and the address re-registered, or a Google-brokered domain changes hands, since the Google IdP trusts its emails.
- **The API already holds app-auth key material.** It receives the provider's client keyring to derive client secrets (`app_auth_oidc.py`), and anything with write access to the platform database can already mint sign-in codes. Holding the ID token signing key too adds no new power over tenant apps.
- **The API already sends mail** through the in-cluster relay (`app/services/mailer.py`). It never raises, and it no-ops where no relay is set.
- **Tenant hosts are reachable from the platform on their public addresses.** The provider design already relies on hairpin NAT for tenant pods reaching the login host, and the same path serves the other direction. The API pod's network policy restricts ingress only.

## Goals / Non-Goals

**Goals:**

- One way to compute a deployment's effective `auth` settings, used by the chart, the daemon and the API, with the same defaults.
- One admission rule (owner, then bound subject, then unbound email) implemented once in the daemon and applied by the broker, the provider and the verifier.
- List edits never touch Helm.
- Revocation that reaches header apps within 30 seconds and OIDC apps through their own logout endpoint, in the removal request itself.

**Non-Goals:**

- OIDC for custom apps. The custom schema refuses `auth.protocol`.
- Roles or groups. The list says who may sign in, not what they may do.
- Exposing the list to the app as a claim or header.
- A CLI command for the list.
- Resending invitations, or invitations with owner-written text.
- Matching the owner by subject. That waits for `keycloak-subject-join-key`.

## Decisions

### D1. The `auth` contract, with OIDC settings in a system-only subtree

```
auth.enabled: bool                    # false
auth.protocol: header | oidc          # header
auth.access: anyone | listed          # anyone
auth.public: [re2]                    # header only; []
auth.oidc.redirectPaths: [path]       # system values only
auth.oidc.nativeRedirectUris: [uri]   # system values only
auth.oidc.pkce: bool                  # system values only; true
auth.oidc.backchannelLogoutPath: path # system values only
```

**Keep `auth` and add keys, rather than rename to `sso`.** Custom deployments and developers' `.freepod.json` files already carry `auth`, so this needs no data migration and no compatibility period. The `sso.*` keys only ever lived in the admin-only immich-sso sandbox, so they are renamed without compatibility.

**Make `protocol` explicit.** Inferring the transport from whether `redirectPaths` exists would let the header flow accept an OIDC app's host.

**Put the OIDC-only keys under `auth.oidc`,** so that "never from user values" is one rule about one subtree. The daemon reads them only from `t.system_values_json`, as it does today for `sso.redirectPaths`.

The defaults live in three places: the daemon's `coalesce(...)` fallbacks, the charts' `values.yaml`, and the API's summary. A test on each side pins them.

### D2. Effective settings come from the serving release

The daemon extends its eligibility queries to return `enabled`, `protocol` and `access`, each `coalesce(release user value, template system value, default)`.

- An unrecognized `protocol` makes the deployment ineligible for both flows.
- An unrecognized `access` is treated as `listed`, which fails closed.

The API computes the same summary for the read model with `template_values.merge_values_scoped` on the applied release. The list endpoint computes `listed_count` with one grouped query, never one query per row.

### D3. One admission function in the daemon

`admit(ctx, deployment, sub, email) (decision, bindEntryID)` applies, in order:

1. **Owner.** `lower(email) = lower(user.email)` of `deployment.user_id` means admit. This needs new column grants on `deployment.user_id` and `"user"(id, email)`.
2. **Bound entry.** An entry with `subject = sub` means admit.
3. **Unbound entry.** An entry with `subject IS NULL AND email = lower(email)` means admit and return the entry, so the caller binds it.
4. Anything else means refuse. That includes an entry with this email that is bound to another subject.

**Binding happens only where a code is issued** (broker header code, provider OIDC code): `UPDATE app_access_entry SET subject=$sub, name=$name, bound_at=now() WHERE id=$id AND subject IS NULL`. If no row is updated, the function re-reads, so a concurrent bind by the same subject still admits. A partial unique index `(deployment_id, subject) WHERE subject IS NOT NULL` keeps one entry per subject.

The verifier calls the same function against its cached copy and never binds. Every verifier session starts with a broker code, so an entry is bound before the verifier sees it.

**Alternative rejected:** storing the owner as an entry. A row can be deleted, so the owner could be locked out, and a future ownership transfer would have to maintain it.

### D4. Data model

- **`app_access_entry`:** `id uuid pk`, `deployment_id → deployment ON DELETE CASCADE`, `email text` (lower case, `CHECK (email = lower(email))`), `subject text NULL`, `name text NULL`, `created_at`, `bound_at NULL`. Unique `(deployment_id, email)`; partial unique `(deployment_id, subject)`.
- **`app_access_invitation`:** `id`, `user_id → user ON DELETE CASCADE`, `sent_at`, with an index on `(user_id, sent_at)`. It doesn't reference the entry, so removing an entry keeps the record.
- **Grants to `caelus_app_auth`:**
  - `SELECT` on `app_access_entry`, plus `UPDATE (subject, name, bound_at)`;
  - `SELECT (user_id)` on `deployment` and `SELECT (id, email)` on `"user"`;
  - nothing on `app_access_invitation`.

### D5. API

Under the existing per-deployment router (`/users/{user_id}/deployments/{deployment_id}/access`, next to `/sftp` and `/database`):

- `GET` returns `{enabled, protocol, access, owner_email, limit: 500, entries: [{id, email, name, created_at, bound_at}]}`. The owner and administrators can call it.
- `POST {email}`, owner only:
  - `422` for an invalid address;
  - `409` for a duplicate (including the owner's own email) or a full list;
  - `409` when the serving release isn't `listed`;
  - `429` when the owner's invitation limit is reached;
  - otherwise `201` with the entry.
  
  It locks the deployment row (`SELECT … FOR UPDATE`) so the 500 bound holds under concurrency, and records the invitation in the same transaction.
- `DELETE /{entry_id}`, owner only, returns `204`. If the entry is bound, the serving release is `oidc` and its template declares a valid `backchannelLogoutPath`, it first signs the person out of the app (D8) and answers `502`, keeping the entry, when that fails.

Administrators read through the same `GET`. Their writes are refused by an explicit owner check, not by the general admin bypass.

### D6. Invitations

The email is sent after commit as a FastAPI background task through `mailer.send_email`. A send failure is logged and doesn't undo the entry. The message is fixed text: the owner's email, `https://<hostname>`, and a line saying to sign in there with a Freepod account using this address, creating one if needed. It uses the owner's email rather than their display name, which is free text a sender could fill with anything.

The limit is a setting, `access_invitations_per_day`, default 100. It counts `app_access_invitation` rows in the last 24 hours across the owner's deployments. A sweep removes rows older than seven days.

### D7. The verifier reads the list, flagged by the chart

A chart rendering `header` with `listed` adds `l=1` to the forward-auth address, which carries no account. For such requests, the verifier:

1. resolves the host to its deployment, including the `preview-` alias, with the broker's logic;
2. takes `{deploymentID, ownerEmail, entries}` from an in-memory cache keyed by the request host, refreshed when older than 30 seconds;
3. runs D3's `admit` against that copy.

Before refusing, it reloads if the copy is more than 5 seconds old. If a reload fails, it keeps the old copy and logs a warning. With no copy at all, it refuses. Keying by host lets one load resolve the host and read the list, so a preview and its app each hold their own copy. The cache is bounded like `patternCache`, and an `l` value other than `1` refuses every signed-in request.

**Why a flag, rather than reading the mode from the database:** `anyone` apps, the common case, keep a request path that never touches the database, exactly as today. The flag can't widen access: the broker checks the database at sign-in, so a chart that forgot the flag would only lose the per-request revocation, never admit a stranger. A flag that disagrees in the strict direction just applies the list.

**Alternatives rejected:**
- The `a=` email list injected by the reconciler. Every list edit would redeploy.
- `LISTEN/NOTIFY` invalidation. With a 30-second bound acceptable, it adds a connection to manage for no visible gain, and refresh-on-refuse covers additions.

### D8. Back-channel logout, synchronously from the API

The API sends the logout token itself, in the `DELETE` request, before it deletes the entry:

1. it signs a token (D9) with the provider's current ID token key;
2. it POSTs `logout_token=<jwt>` to `https://<hostname><path>`, with a 10-second timeout, TLS verified, and no redirects followed;
3. only a `2xx` answer lets the deletion commit. Anything else, a network error included, answers `502` naming the app, and the entry stays.

The entry row is locked for the duration, so two removals of one entry send one token.

**Why synchronous:** an owner who removes someone learns at once whether the app signed them out, and nothing needs to remember a delivery that is still owed. The cost is that a person cannot be removed from an OIDC app while that app is down. Header apps and unbound entries send nothing, so they never fail this way.

**Alternatives rejected:**
- A transactional outbox delivered by app-auth. It survives the app being down, but needs a table, grants, a worker, claiming across replicas and a retry schedule, all to deliver a token whose loss only leaves an existing session alive.
- An internal app-auth endpoint that signs tokens for the API. It keeps the key in one place, but adds a listener, a shared secret and a second hop that can fail, to protect against an API compromise that already owns the database.

### D9. Logout tokens

The API signs with the first key of the provider's signing keyring, which tf passes to the API pod as it passes the client keyring. The header is `typ: logout+jwt` with `kid`, the key's RFC 7638 thumbprint as app-auth computes it for the JWKS; a test on each side pins one vector. Its claims are `iss` (the provider's issuer), `aud` (the client ID), `iat`, `exp = iat + 120`, `jti` (random), `sub`, and `events: {"http://schemas.openid.net/event/backchannel-logout": {}}`, with no `sid` and no `nonce`. Discovery, served by app-auth, adds `backchannel_logout_supported: true` and `backchannel_logout_session_supported: false`.

### D10. Where each flow checks access

- **Header broker:** checks after the identity provider's callback, before the consent page; again before the code is issued, where it binds; and the verifier then checks every request.
- **OIDC provider:** checks after the identity provider's callback, before consent, and again where the code is issued, where it binds. A code is issued from the consent POST, or straight from the callback when consent already exists.
  - A refusal renders the no-access page on the login host.
  - With `prompt=none`, a refusal redirects back with `error=access_denied`.
  - The token endpoint and userinfo check again.
- **Pages:** the no-access page gains the listed wording and stays one template, in the placeholder look, on both hosts. On the login host it names the app by its host, since the broker never sees the chart's `n=`, and accepting a name in the sign-in URL would let anyone put any name on the login host. Its sign-out link ends the identity provider's session: the broker's `/logout?host=` for a header app, which returns to the app's sign-in, and `/oidc/logout` for an OIDC app.

### D11. App Studio

- The template's system values become `auth: {enabled: true, access: listed}`.
- The chart:
  - fails unless `enabled && protocol == header && access == listed`;
  - drops `$owner`, `$allowed` and `a=`, and adds `l=1`.
- Existing studios have no entries, so they admit only their owners at every step of the rollout.

### D12. Custom chart and catalog

- `custom` adds `auth.access` to `values.schema.json` and to the catalog template's user schema, which mirrors it, and renders `l=1` when it is `listed`. The custom template sets no `auth` system values, because the defaults are already right.
- Catalog validation gains a rule: if a template's system values set `auth.enabled: true`, they must also set `auth.access`.

### D13. UI

- **`DeploymentRow`** reads the read model's `auth` summary:
  - `listed` gives the Access button, the "You and N people" fact, and the collapsed-row summary.
  - `anyone` gives "Managed in {appName}".
- **`AccessDialog`** (2a/2b/2c on the canvas) loads the list with React Query, filters on the client, and shows search and filters past 10 entries. It maps API errors to the field.
- **The admin `DeploymentDialog`** gains a read-only `AccessPanel` beside `SftpAccessPanel`.
- Product-specific text is limited to the app name and address.

## Risks / Trade-offs

- **[Owner matched by email]** Changing the owner's email would lose them owner admission until the user row follows. → Keycloak forbids changing the username, and email is the username. Subject matching follows `keycloak-subject-join-key`.
- **[An unbound entry admits whoever first holds the address]** → That's the meaning of inviting an address. Binding closes the window after the first sign-in, and the dialog shows which entries are still unbound.
- **[Invitations as a spam channel]** → Fixed text with no owner-written content, the owner's own address in the message, a daily cap, and a recipient who can only ever get the same short message.
- **[Verifier load]** One query per listed deployment every 30 seconds, plus rare refusal reloads. → Bounded cache. `anyone` apps are unaffected.
- **[The app ignores or mishandles logout tokens]** → The token and userinfo checks keep the person from getting new tokens. Nextcloud and Immich were read to confirm `sub`-only handling.
- **[An OIDC app that is down blocks removals]** → The owner sees which app could not be reached and retries when it runs. Only bound entries of `oidc` apps with a logout path are affected.
- **[The API holds the ID token signing key]** → An API compromise could mint ID tokens for tenant apps. It could already mint sign-in codes through the database, so the boundary was not there to keep.
- **[Removing an entry of a header app leaves its session cookie valid for its lifetime]** → The verifier refuses it on every request after the cache refresh, so the cookie is useless.
- **[A stale cache during a database outage keeps a removed person in]** → That's the stated trade-off: the verifier keeps a known list rather than locking everyone out. Once the database is reachable again, the next refresh applies the removal.

## Migration Plan

1. **Alembic migration** for the two tables, then the bootstrap SQL grants. They are additive, so the running daemon is unaffected.
2. **Daemon release** that:
   - reads `auth.*` everywhere and adds `auth.protocol` to header eligibility;
   - reads the provider's keys from `auth.oidc`;
   - adds the access checks, the `l=1` handling and the discovery flags;
   - **keeps `a=`** until step 5.

   Its `ssoClient` stops reading `sso.*`, so the immich-sso deployments must move in step 3 straight after this rollout. They are admin-only sandboxes, so a few minutes of broken sign-in is acceptable.
3. **immich-sso chart 0.1.2 and a new template version** on `auth.*`; upgrade the dev and prod sandbox deployments.
4. **API and UI:** the read-model summary, the access endpoints, invitations, logout tokens with the signing keys on the API pod, and the dialog.
5. **Custom chart and App Studio chart versions with the catalog templates; upgrade App Studio deployments.** Once none renders `a=`, remove `allowCache` and `a=` from the daemon and release it.

**Rollback:**
- Each step's previous image or chart remains deployable.
- Up to step 5, an older daemon simply ignores `l=1` and admits any signed-in account to listed header apps. So step 5's App Studio upgrade must not be rolled back past the daemon that understands `l=1`.

## Open Questions

None. The `sid` question is settled above: both target apps accept `sub`-only tokens.
