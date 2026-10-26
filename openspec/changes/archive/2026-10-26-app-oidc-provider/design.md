## Context

See proposal.md for why. The facts this design rests on:

- **The broker already does the hard half.** It runs the authorization code
  flow with PKCE against Keycloak through `freepod-apps-{prod,dev}`, rejects
  unverified email, checks that a host is an eligible deployment from its
  applied release, and asks for consent per (Keycloak subject, deployment)
  (`daemons/app-auth/broker.go`, `store.go`). Its flow state travels in AEAD
  cookies sealed per purpose (`seal.go`).
- **Keycloak cannot hold per-deployment redirect URIs for us.** Tenant hosts are
  `<app>-<handle>.freepod.app` (`tf/app/locals.tf`) or custom domains, and
  Keycloak has no way to express custom domains. Per-deployment clients are
  the per-tenant identity-provider state we refuse.
- **A tenant host serves content from every user of its app**, not just its
  owner: Nextcloud shares, BookStack pages, Discourse posts, plus whatever open
  redirects the app has. Owning the host does not make every path on it a safe
  place to deliver an authorization code.
- **Credentials never travel through Helm values.** The provisioner logs merged
  values and Helm persists them in a tenant-namespace release Secret, so the
  reconciler publishes database and bucket credentials as Kubernetes Secrets
  and injects only references (`_ensure_object_storage`, `_ensure_database`).
  `deployment_release.values_json`, which the app-auth role can read, therefore
  never holds a secret either.
- **Derived credentials have a precedent.** Registry pull passwords are an HMAC
  of the user id under a per-environment key (`registry_tokens.pull_password`),
  so nothing per user is stored.
- **Terraform already generates app-auth's keys** (`random_bytes` session keys in
  `tf/app/app-auth/main.tf`), so new key material needs no manual secret.
- **Tenant pods reach the login host on its public address.** They have full
  internet access and hairpin NAT at the edge is reliable, so the back-channel
  token and JWKS calls need nothing special.
- **The consent page's CSP has `form-action 'self' https:`** (`pages.go`), and
  Chromium applies `form-action` to the redirect that answers the consent POST.
  A redirect to a custom scheme such as `app.immich:` is blocked today. That
  was tested in Chromium.
- **The catalog apps can all do PKCE except one.** Immich uses it whenever
  discovery advertises S256. BookStack always uses it. Nextcloud `user_oidc`
  has it on by default. PhotoPrism uses it when advertised. Vaultwarden
  (`SSO_PKCE`) and Discourse (`openid_connect_use_pkce`) can be switched on by
  their charts. Only a Mattermost GitLab shim could not use it.
- **BookStack verifies only RS256 ID tokens.** Most apps discover endpoints from
  `/.well-known/openid-configuration` and authenticate at the token endpoint
  with either `client_secret_basic` or `client_secret_post`.

## Goals / Non-Goals

**Goals:**

- A chart can configure any standard OIDC client library against Freepod with
  an issuer, a client ID and a client secret, plus the callback paths its app
  uses.
- Nothing in Keycloak, and no per-deployment row, exists to make a deployment
  an OIDC client.
- A credential, code or token issued to one deployment is useless at any other.
- An authorization code is delivered only to the exact redirect URI the
  product declares, as RFC 9700 §2.1 requires.
- No behavior change for anything that does not set `sso.enabled`.

**Non-Goals:**

- **Access control.** As with header authentication today, any verified
  Freepod account may sign in. Apps that gate in-app (auto-registration off)
  can adopt this as is. The owner-managed allowlist ("people I list") is its
  own later change.
- **Revoking app sessions.** Without refresh tokens, and with apps keeping
  their own sessions, nothing here ends a signed-in app session after an
  account is deleted or banned. That gap is accepted only until the allowlist
  change, which must take it on, most likely with OIDC Back-Channel Logout
  (Immich and Nextcloud `user_oidc` both support it). It is not an ordinary
  non-goal.
- **Refresh tokens and `offline_access`.** Adding them later is additive.
- **Charts.** Immich and Nextcloud get sandbox copies (`products/immich-sso`,
  `products/nextcloud-sso`) as separate, non-catalog products in later changes.
- **The GitLab-shaped user endpoint for Mattermost.**
- **Dynamic client registration, the implicit and hybrid flows, pairwise
  subjects, `request` objects, front-channel logout.**
- **`preferred_username`.** It is omitted. It may be added later only if it
  holds an immutable, unique value. It must never be derived from the part of
  the email before the `@`, because Matrix uses it as the account name, so
  `alice@a` and `alice@b` would collide and one could take over the other.
- **`X-Freepod-Jwt`.** It stays reserved. If it later shares this JWKS, it must
  carry its own `typ`, since both kinds would have the deployment as `aud`.

## Decisions

### D1: One process, a second role for the broker's listener

The provider's endpoints live on the broker's listener, at the login host,
under `/oidc/`, plus discovery at `/.well-known/openid-configuration`. The
issuer is `https://login.<domain>`, which is the value `APP_AUTH_LOGIN_URL`
already holds.

The provider shares the broker's Keycloak leg, consent page, consent table and
sealing keys, so splitting it into another deployable would duplicate the
security boundary the app-authentication design kept in one place (its D3).
The verifier listener is untouched.

Chosen over an off-the-shelf provider library (`zitadel/oidc`, Ory Fosite):
those assume a client store and a storage interface for every artifact, and
we would implement both against the same two queries anyway. What the provider
needs on top of the existing flow glue is small: parse and validate the
authorization request, one code table, a token endpoint, a JWT signer. Revisit
if refresh tokens, PAR or other grant types are needed.

```
app (browser)          broker /oidc (login host)                 Keycloak
  │ GET /oidc/authorize?client_id=<dep>&redirect_uri&state&nonce&code_challenge
  │ ──────────────────▶ client eligible? redirect_uri exact?     (DB)
  │ ◀── 302 Keycloak authorize (broker's own state, PKCE)
  │ ────────────────────────────────────────────────────────────▶ SSO / login
  │ ◀──────────────────────────────────────────────────────────── 302 /callback
  │ GET /callback ─────▶ token exchange, email_verified,
  │                      eligible again?, consent? (DB)
  │ ◀── 302 <redirect_uri>?code=<one-time>&state      code row (DB)
app (server)
  │ POST /oidc/token (code, client_id, client_secret, redirect_uri, code_verifier)
  │ ──────────────────▶ secret = HMAC(key, client_id)? code row matches? (DB)
  │ ◀── id_token (RS256, aud=<dep>), access_token
  │ GET /oidc/userinfo (Bearer) ──▶ opens the sealed access token, eligible?
```

`/callback` stays the single Keycloak redirect URI. The sealed flow cookie
records which kind of sign-in it is (verifier code handoff, or OIDC), and the
callback finishes accordingly.

### D2: `sso.enabled`, and the template must declare support

A deployment is an eligible OIDC client when it is not deleted, the template
of the release it serves declares at least one valid callback path (D4) in the
system value `sso.redirectPaths`, and that release has `sso.enabled` true: the
release's user value when it sets one, otherwise the template's system value,
otherwise false. That is the precedence of the reconciler's Helm merge
(`merge_values_scoped` takes template system values as defaults, user values
over them, and only its own `caelus` block last), so the broker agrees with
what the release rendered, also while a rollout is in flight, and the
reconciler publishes credentials on the same rule. A template that must force
the switch leaves it out of its user values schema.

The same correction applies to `auth.enabled`. `app-auth-owner-and-preview`
D1 read it as "template system value, then user value" on the belief that
`merge_values_scoped` merges template system values last; it merges them
first. The two orders disagree only when a template sets `auth.enabled` and
its schema lets users set it too, which no product does today (App Studio's
schema is closed and has no `auth`), so correcting the query changes nothing
that serves now and keeps the broker and the edge from ever disagreeing.

Requiring `sso.redirectPaths` makes SSO something a product declares, not
something any deployment can switch on. Template meta-validation does not
enforce closed user-value schemas, so without this check a template with an
open schema would let a user turn a deployment into a client. With it, only a
template's author can.

Why a new key rather than reusing `auth.enabled`: `auth.enabled` means "put the
forward-auth verifier in front of every request". A catalog app with SSO must
not get that, because its native clients would see `401`. The two are
independent; a chart may in principle use both.

Eligibility is looked up by deployment ID (the client ID), not by host, and the
host is then taken from that deployment's row. Preview hostnames do not apply.

### D3: Client credentials are derived, never stored

- `client_id` = the deployment's ID (its UUID, as text).
- `client_secret` = base64url(HMAC-SHA256(key, `"app-oidc-client:v1:" || client_id`)).

The key is a keyring, in the format of `APP_AUTH_SESSION_KEYS`
(`id:base64,…`, current first). The reconciler derives with the first key. The
broker accepts a secret derived with any key in the ring, and compares in
constant time. Rotation: add a new key in front, apply, let the reconciler
republish every SSO deployment's Secret, then drop the old key. That works
only if every chart re-applies its OIDC settings on every start, because
Immich and Nextcloud keep them in their own databases. The chart contract
requires that.

Terraform generates the key and hands the same keyring to the API
(`APP_AUTH_OIDC_CLIENT_KEYS`) and app-auth. The broker is not the place to
fetch secrets from, and the API already derives secrets the same way.

A single deployment's secret cannot be rotated: turning SSO off and on gives
the same one. That is accepted. With exact redirect URIs (D4) and required
PKCE (D5), a leaked client secret on its own buys almost nothing. Getting a
code still takes a victim's session and consent, delivered to the app's own
callback.

Rejected: **a client row per deployment** with a hashed secret. It allows
per-deployment revocation and rotation, but brings a lifecycle (create on
opt-in, delete with the deployment, drift) for little gain.

### D4: Redirect URIs match exactly

An authorization request's `redirect_uri` is accepted only when it equals,
byte for byte, one of:

1. `https://<deployment hostname, from its row><path>` for each `path` in the
   serving release's template system value `sso.redirectPaths`. A path is
   fixed per product (BookStack's is `/oidc/callback`). The hostname comes
   from the deployment row in lowercase, so custom domains work with no
   configuration. The broker honors a path only when it starts with `/` but
   not `//`, and holds no `?`, `#`, `\` or control character. It then parses
   the joined URI and requires its host to equal the deployment's hostname,
   with no userinfo and no port. A path that fails either check is ignored and
   logged. Without this, the join itself can move the host: `@evil.example/cb`
   yields host `evil.example`, and `.evil.example/cb` yields
   `<hostname>.evil.example`; or
2. one of the URIs in the template system value `sso.nativeRedirectUris`. Each
   must use a private-use scheme, never `http` or `https`, in reverse-domain
   form with at least one `.` (RFC 8252 §7.1), such as
   `app.immich:///oauth-callback`. A template value that breaks this is
   ignored and logged.

Both read only template system values, never user values, so a tenant cannot
add a redirect. Neither rule can name a collector on another host, which would
receive codes for every deployment of the template while the consent page
names the deployment's own host. The upgrader agent edits catalog YAML, so
both rules are enforced by the broker, not trusted to review. The Immich pilot may not need
rule 2 at all, since Immich's `https://<host>/api/oauth/mobile-redirect`
override fits rule 1.

Why not "any path on the host": an attacker starts a real login at app X to
get their own state and PKCE challenge, then builds an authorize link for X
whose `redirect_uri` is a path on X's host that leaks its URL (a page users can
write, or an open redirect). A victim who has consented before and has a
Keycloak session is redirected with nothing to click, and the code leaks. The
attacker redeems it through their own session at X's real callback and is
signed in as the victim. PKCE does not help, because the attacker made the
challenge. Free-form queries are worse still: `redirect_uri=https://host/cb?code=ATTACKER`
logs the victim into the attacker's account.

Until the client and redirect URI are validated, every error is a page on the
login host and never a redirect, as everywhere in the broker. After that,
errors go back to the redirect URI as `error=` per RFC 6749 §4.1.2.1.

The token endpoint requires `redirect_uri` to equal the one the code was
issued for.

### D5: Codes in their own table, PKCE required

`app_auth_oidc_code(code_hash, deployment_id, redirect_uri, subject, email,
name, nonce, code_challenge, auth_time, expires_at)`. Hash-only storage,
60-second lifetime, redemption by `DELETE … RETURNING` so concurrent
redemptions cannot both succeed, and cleanup by the existing purge loop. That
mirrors `app_auth_code`.

A separate table rather than new nullable columns on `app_auth_code`: the
verifier redeems those by host and login nonce, these by client and redirect
URI, and a code of one kind must never redeem as the other.

PKCE with `S256` is required on every authorization request. `plain` is
refused. A template may opt out with the system value `sso.pkce: false`, which
exists for the Mattermost GitLab shim only. The opt-out never applies to rule 2
redirect URIs, because RFC 8252 §8.1 requires PKCE for custom schemes. At the
token endpoint, a code issued with a challenge requires the matching
`code_verifier`, and a token request that carries a `code_verifier` for a code
issued without one is refused (RFC 9700 §2.1.1), so PKCE cannot be downgraded.

### D6: Tokens

- **ID token**: a JWT signed RS256, header `typ: JWT` and `kid`. Claims `iss`,
  `aud` (= `client_id`), `azp` (= `client_id`), `sub`, `email`,
  `email_verified` (always `true`, because the broker refuses unverified
  emails), `name`, `iat`, `exp` (= `iat` + 300 s), `auth_time` (taken from
  Keycloak's ID token, carried in the code row), and `nonce` when the request
  had one. RS256 because the OIDC core spec makes it the algorithm every
  provider must support, and BookStack verifies nothing else.
- **Access token**: opaque to the app, sealed with the broker's keyring under
  its own purpose (`oidc-access`), holding the identity and `client_id`, valid
  for ten minutes. Apps call userinfo once around login, so a short life costs
  nothing. `/oidc/userinfo` opens it, re-checks that the client is still an
  eligible deployment, and answers the same claims as the ID token. A
  deployment that is deleted or turns SSO off stops answering at once.
  Nothing is stored, and nothing in the token is usable outside userinfo.
- **Signing key**: an RSA-2048 key generated by Terraform (`tls_private_key`),
  passed as PEM in `APP_AUTH_OIDC_SIGNING_KEYS`, a keyring whose first key
  signs. `/oidc/jwks` publishes the public half of every key in the ring.
  Rotation adds a key in front and drops the old one after ID tokens signed
  with it have expired (minutes).
- **Subject** is the Keycloak subject, unchanged: the value the verifier sends
  as `X-Freepod-User` and the key of consent records. Pairwise subjects would
  stop apps from correlating users across deployments. But they also get the
  user's email, which correlates anyway.

### D7: Consent is the existing consent

The provider discloses exactly the claims the consent page already names
(`sub`, `email`, `name`), so a consent recorded for a deployment through either
path counts for both. The consent page shows the deployment's hostname, not
the redirect URI.

When the redirect URI uses a rule 2 scheme, the consent response's
`form-action` adds that scheme (for example `app.immich:`), so the redirect
after the consent POST is not blocked. Only the validated scheme is added, and
only on that response.

### D8: Request handling

- **Client authentication**: the token endpoint accepts `client_secret_basic`
  and `client_secret_post`, the two any app library uses. It refuses requests
  that offer both. Unknown or ineligible clients get `invalid_client` with no
  hint about which part failed.
- **Bounds**: every authorization request seals its parameters into a flow
  cookie on the login host, so their sizes are capped before anything is set:
  `state` at 512 bytes, `nonce` at 256, `redirect_uri` at 2048, and
  `code_challenge` at the 43 characters an S256 challenge has. Anything larger
  is `invalid_request`. That keeps a hostile page from filling the login host's
  cookie jar until it answers `431`. Token request bodies are capped as the
  consent form's is.
- **`prompt=none`** is passed to Keycloak, so a missing Keycloak session comes
  back as `login_required`. When the broker's own consent is missing, it
  answers `consent_required` instead of showing the consent page.
- **`max_age`** is passed through to Keycloak, and `auth_time` comes from
  Keycloak's ID token.

### D9: End session

`/oidc/logout` accepts `client_id`, `id_token_hint`, `post_logout_redirect_uri`
and `state`. It honors the redirect only when `id_token_hint` is an ID token
this provider signed, checked against its own JWKS (ignoring `exp`), with `aud`
equal to `client_id`, and when the redirect is exactly the deployment's
`https://<hostname>/` or matches the D4 rules. It then reuses the broker's
existing Keycloak end-session round trip, landing on `/signed-out`, which
forwards to the validated URI. Otherwise the user ends on the broker's
"You're signed out" page.

### D10: What the reconciler gives a chart

For a deployment whose merged values have `sso.enabled: true`, the reconciler:

- publishes Secret `<deployment>-oidc` in the tenant namespace with
  `OIDC_ISSUER`, `OIDC_CLIENT_ID` and `OIDC_CLIENT_SECRET`, labelled like the
  database Secret;
- injects `caelus.oidc.{issuer, clientId, secretName}` into the chart values.

A deployment without `sso.enabled` gets neither, and an existing Secret is
deleted when a deployment turns SSO off. The issuer is injected as a plain
value because charts often need it in a config file, and it is public.

Charts must re-apply their OIDC settings from the Secret on every start (D3),
and must turn the app's local sign-up off when they rely on the app to decide
who gets in (D11).

### D11: What a chart owes when the app decides

Freepod registration is open, so for "app decides" products the app's own
sign-up switch and its account linking are the only barrier. Before such a
chart enables SSO:

- an uninvited Freepod account must be shown to be refused, by a test on dev;
- local sign-up with an unverified email must be off, or an attacker could
  pre-create an account under someone else's address that SSO later links to;
- apps that pin `sub` after the first link are preferred over those that match
  by email on every login. Keycloak's Google sign-in trusts Google's email,
  so whoever buys an expired domain can get that domain's addresses back as
  verified emails under a new subject.

## Risks / Trade-offs

- **[One shared client key per environment]** Leaking the key leaks every
  deployment's client secret. It lives in the same places as the session keys
  and the registry pull key. With exact redirects and required PKCE, a client
  secret alone cannot obtain codes.
- **[Any Freepod account can sign in, and sessions outlive accounts]** Until the
  allowlist change ships, only apps whose own registration can be turned off
  should enable SSO, and deleting a Freepod account does not end its existing
  app sessions. The sandbox Immich copy (auto-registration off) is the first
  user.
- **[Keycloak subject changes]** Rebuilding the realm reissues every subject.
  Apps that pin `sub` would then refuse or duplicate users until relinked.
  Email fallback would recover them, but it is the same mechanism D11 warns
  about, so it is not counted as a safeguard. The keycloak-subject-join-key
  change accepts the same risk for the platform.
- **[Exact paths need per-product knowledge]** Each chart change must find its
  app's callback path. It is fixed per product and documented by each app, so
  this is a line in the template, not a burden.
- **[Broker restart blocks new app sign-ins]** As for header authentication,
  the broker runs one replica. Signed-in app sessions are the app's own and
  unaffected.

## Migration Plan

Additive. Nothing changes until a deployment's template declares
`sso.redirectPaths` and it sets `sso.enabled`.

1. Migration (`app_auth_oidc_code`) and role grants.
2. Terraform: client keyring, signing key, new env on app-auth and the API.
3. New daemons image, rolled to dev with `-var app_auth_image=…`.
4. API release with the reconciler change. No deployment has `sso.enabled`, so
   nothing is published yet.
5. Verify on dev with a throwaway OIDC client (task 6), then prod.

Rollback: revert the image pin. Without the provider, apps with `sso.enabled`
lose SSO login, and there are none until the sandbox charts land.
