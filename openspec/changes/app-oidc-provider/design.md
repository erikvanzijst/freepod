## Context

See proposal.md for why. The facts this design rests on:

- **The broker already does the hard half.** It runs the authorization code
  flow with PKCE against Keycloak through `freepod-apps-{prod,dev}`, rejects
  unverified email, checks that a host is an eligible deployment from its
  applied release, and asks for consent per (Keycloak subject, deployment)
  (`daemons/app-auth/broker.go`, `store.go`). Its flow state travels in AEAD
  cookies sealed per purpose (`seal.go`).
- **Keycloak cannot hold per-deployment redirect URIs** for our hostnames
  (app-authentication design, Context), and per-deployment clients are the
  per-tenant identity-provider state we refuse.
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
- **Tenant egress allows the public internet minus internal ranges**
  (`network_policy.py`), which is how an app pod would reach
  `https://login.<domain>` for the back-channel token and JWKS calls. Hairpin
  NAT at the edge is reliable, so tenant pods reach the login host on its
  public address like any other site.
- **Catalog apps differ in what they accept.** BookStack verifies only RS256 ID
  tokens. Immich's mobile app needs `app.immich:///oauth-callback`. Most apps
  discover endpoints from `/.well-known/openid-configuration` and authenticate
  at the token endpoint with either `client_secret_basic` or
  `client_secret_post`.

## Goals / Non-Goals

**Goals:**

- A chart can configure any standard OIDC client library against Freepod with
  an issuer, a client ID and a client secret, and nothing else.
- Nothing in Keycloak, and no per-deployment row, exists to make a deployment
  an OIDC client.
- A credential or token issued to one deployment is useless at any other.
- No behavior change for anything that does not set `sso.enabled`.

**Non-Goals:**

- **Access control.** As with header authentication today, any verified
  Freepod account may sign in. Apps that gate in-app (auto-registration off)
  can adopt this as is. The owner-managed allowlist ("people I list") is its
  own later change.
- **Refresh tokens and `offline_access`.** Apps keep their own sessions after
  login. Adding refresh tokens later is additive.
- **Charts.** Immich and Nextcloud get sandbox copies (`products/immich-sso`,
  `products/nextcloud-sso`) as separate, non-catalog products in later changes.
- **The GitLab-shaped user endpoint for Mattermost.**
- **Dynamic client registration, the implicit and hybrid flows, pairwise
  subjects, `request` objects, front- and back-channel logout.**
- **`X-Freepod-Jwt`.** It stays reserved. Its JWKS can be the same one later.

## Decisions

### D1: One process, a second role for the broker's listener

The provider's endpoints live on the broker's listener, at the login host,
under `/oidc/`, plus discovery at `/.well-known/openid-configuration`. The
issuer is `https://login.<domain>`, which is the value
`APP_AUTH_LOGIN_URL` already holds.

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
  │ GET /oidc/authorize?client_id=<dep>&redirect_uri&state&nonce
  │ ──────────────────▶ client eligible? redirect_uri allowed?   (DB)
  │ ◀── 302 Keycloak authorize (broker's own state, PKCE)
  │ ────────────────────────────────────────────────────────────▶ SSO / login
  │ ◀──────────────────────────────────────────────────────────── 302 /callback
  │ GET /callback ─────▶ token exchange, email_verified,
  │                      eligible again?, consent? (DB)
  │ ◀── 302 <redirect_uri>?code=<one-time>&state      code row (DB)
app (server)
  │ POST /oidc/token (code, client_id, client_secret, redirect_uri, code_verifier?)
  │ ──────────────────▶ secret = HMAC(key, client_id)? code row matches? (DB)
  │ ◀── id_token (RS256, aud=<dep>), access_token
  │ GET /oidc/userinfo (Bearer) ──▶ opens the sealed access token
```

`/callback` stays the single Keycloak redirect URI. The sealed flow cookie
records which kind of sign-in it is (verifier code handoff, or OIDC), and the
callback finishes accordingly.

### D2: `sso.enabled`, read the way `auth.enabled` is read

A deployment is an eligible OIDC client when it is not deleted and the release
it serves has `sso.enabled` true: the template's system value when the template
sets one, otherwise the release's user value, otherwise false. That is the
existing eligibility rule with a different key, so the broker agrees with what
the release rendered while a rollout is in flight.

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
republish every SSO deployment's Secret (the apps pick it up on restart), then
drop the old key.

Terraform generates the key and hands the same keyring to the API
(`APP_AUTH_OIDC_CLIENT_KEYS`) and app-auth. The broker is not the place to
fetch secrets from, and the API already derives secrets the same way.

Rejected: **a client row per deployment** with a hashed secret. It allows
per-deployment revocation, but brings a lifecycle (create on opt-in, delete
with the deployment, drift) for no gain: a deployment's credentials already
stop working the moment it stops being eligible.

### D4: Redirect URIs are derived from the deployment

An authorization request's `redirect_uri` is accepted when either:

1. it is an absolute `https` URI with no userinfo, no fragment and the default
   port, whose host equals the deployment's hostname, case-insensitively; any
   path and query are accepted; or
2. it equals, exactly, one of the strings in the serving release's template
   system value `sso.redirectUris`.

Rule 1 needs no configuration and covers custom domains. Any path on the
app's own host is safe to accept, since the host already belongs to the app.
Rule 2 exists for native clients' custom schemes. It reads only template system
values, never user values, so a tenant cannot add an arbitrary redirect.

Until the client and redirect URI are validated, every error is a page on the
login host and never a redirect, as everywhere in the broker. After that,
errors go back to the redirect URI as `error=` per RFC 6749 §4.1.2.1.

The token endpoint requires `redirect_uri` to equal the one the code was
issued for.

### D5: Codes in their own table

`app_auth_oidc_code(code_hash, deployment_id, redirect_uri, subject, email,
name, nonce, code_challenge, expires_at)`. Hash-only storage, 60-second
lifetime, redemption by `DELETE … RETURNING` so concurrent redemptions cannot
both succeed, and cleanup by the existing purge loop. That mirrors
`app_auth_code`.

A separate table rather than new nullable columns on `app_auth_code`: the
verifier redeems those by host and login nonce, these by client and redirect
URI, and a code of one kind must never redeem as the other.

PKCE: when the authorization request carries `code_challenge`, the method must
be `S256` and the token request must carry the matching `code_verifier`.
`plain` is refused. PKCE is optional because every client is confidential.

### D6: Tokens

- **ID token**: a JWT signed RS256, header `kid`. Claims `iss`, `aud`
  (= `client_id`), `azp` (= `client_id`), `sub`, `email`, `email_verified`
  (always `true`, because the broker refuses unverified emails), `name`, `iat`,
  `exp` (= `iat` + 300 s), `auth_time`, and `nonce` when the request had one.
  RS256 because the OIDC core spec makes it the algorithm every provider must
  support, and BookStack verifies nothing else.
- **Access token**: opaque to the app, sealed with the broker's keyring under
  its own purpose (`oidc-access`), holding the identity and `client_id`, valid
  for one hour. `/oidc/userinfo` opens it and answers the same claims as the ID
  token. Nothing is stored, and nothing in the token is usable outside userinfo.
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

### D8: Client authentication and request hygiene

The token endpoint accepts `client_secret_basic` and `client_secret_post`, the
two any app library uses. It refuses requests that offer both. Unknown or
ineligible clients get `invalid_client` with no hint about which part failed.
Request bodies are capped as the consent form's is. `prompt=none` is answered
with `login_required` when Keycloak would have to show a page, which falls out
of passing `prompt` through to Keycloak.

### D9: End session

`/oidc/logout` accepts `client_id`, `post_logout_redirect_uri` and `state`.
The redirect is validated by the D4 rules. It then reuses the broker's
existing Keycloak end-session round trip, landing on `/signed-out`, which now
forwards to the validated URI. `id_token_hint` is accepted and ignored, since
the broker keeps no tokens to check it against. Without a valid redirect, the
user ends on the broker's "You're signed out" page.

### D10: What the reconciler gives a chart

For a deployment whose merged values have `sso.enabled: true`, the reconciler:

- publishes Secret `<deployment>-oidc` in the tenant namespace with
  `OIDC_ISSUER`, `OIDC_CLIENT_ID` and `OIDC_CLIENT_SECRET`, labelled like the
  database Secret;
- injects `caelus.oidc.{issuer, clientId, secretName}` into the chart values.

A deployment without `sso.enabled` gets neither, and an existing Secret is
deleted when a deployment turns SSO off. The issuer is injected as a plain
value because charts often need it in a config file, and it is public.

## Risks / Trade-offs

- **[One shared client key per environment]** Leaking the key leaks every
  deployment's client secret. It lives in the same places as the session keys
  and the registry pull key, and the client secret alone is not enough to sign
  anyone in: it still takes a user's Keycloak session and consent to obtain a
  code, and redirects are bound to the deployment's host.
- **[Any Freepod account can sign in]** Until the allowlist change ships, only
  apps whose own registration can be turned off should enable SSO. The
  sandbox Immich copy (auto-registration off) is the first user.
- **[Keycloak subject changes]** Rebuilding the realm reissues every subject.
  Apps that link on `sub` alone would then create new accounts. Apps that fall
  back to email (Immich, Vaultwarden, Discourse) recover. The
  keycloak-subject-join-key change already accepts the same risk for the
  platform.
- **[Broker restart blocks new app sign-ins]** As for header authentication,
  the broker runs one replica. Signed-in app sessions are the app's own and
  unaffected.

## Migration Plan

Additive. Nothing changes until a deployment sets `sso.enabled`.

1. Migration (`app_auth_oidc_code`) and role grants.
2. Terraform: client keyring, signing key, new env on app-auth and the API.
3. New daemons image, rolled to dev with `-var app_auth_image=…`.
4. API release with the reconciler change. No deployment has `sso.enabled`, so
   nothing is published yet.
5. Verify on dev with a throwaway OIDC client (task 6), then prod.

Rollback: revert the image pin. Without the provider, apps with `sso.enabled`
lose SSO login, and there are none until the sandbox charts land.

## Open Questions

- Whether `preferred_username` should be sent, and what it would hold. The
  Freepod handle is nullable and app-only users may have no platform user row,
  so it is left out for now.
