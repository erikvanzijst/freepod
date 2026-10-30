# app-auth — "Sign in with Freepod" for tenant apps

A deployment whose chart renders the app-auth middlewares and that has
`auth.enabled` (a user value, or a system value of its template) gets verified
identity headers (`X-Freepod-User`, `X-Freepod-Email`, `X-Freepod-Name`) on
every request, with Freepod's Keycloak as the identity provider. A deployment
whose template declares `auth.oidc.redirectPaths` and that has `auth.protocol:
oidc` is instead an OpenID Connect client of this service. Either way,
`auth.access: listed` admits only the owner and the deployment's access list,
which the API edits. It has three roles:

- **The verifier** (`:8080/verify`) is Traefik's forward-auth endpoint for
  every auth-enabled app. It checks a host-bound session cookie, strips it and
  every platform cookie from the request, and sets the identity headers, or
  answers with a redirect to sign in (navigations) or `401` (everything else).
  Its address carries the deployment's public paths (`p`) and, optionally,
  whether the access list applies (`l=1`), the accounts allowed in (`a`) and
  the app's name for the no-access page (`n`). It also serves
  `/.freepod/auth/{login,callback,logout}` on each app host, from inside
  forward-auth. The per-request path reads the database only to refresh a
  listed host's access list, at most every 30 seconds, and keeps its last
  copy through an outage.
- **The broker** (`:8081`, public at `login.<domain>`) is the only party that
  talks OIDC to Keycloak, through one client per environment
  (`freepod-apps-{prod,dev}`) with one redirect URI. It checks that the host is
  an auth-enabled deployment, applies its access list when it is `listed`,
  asks for consent once per user and deployment, and hands the app host a
  single-use code bound to that host and to the browser that started signing
  in. Issuing a code ties an access list entry to the subject that first signs
  in with it. `preview-<label>.<rest>` signs in as the deployment at
  `<label>.<rest>`.
- **The provider** (also `:8081`, issuer `https://login.<domain>`) is an OpenID
  Provider for SSO-enabled deployments, under `/oidc/` plus discovery. It signs
  users in through the broker's Keycloak leg and consent, and has no client
  records: a client's ID is its deployment's ID, its secret is derived, and its
  redirect URIs are the template's declared paths on the deployment's
  hostname. The reconciler publishes each deployment's credentials in a
  Secret. The API, not this service, sends back-channel logout tokens when an
  owner removes someone, signed with the provider's key.

**Logout** (`/.freepod/auth/logout?rd=…`) clears the app host's session, then
goes through the broker's `/logout` to Keycloak's end-session endpoint, so the
next sign-in asks for credentials and can pick another account. Keycloak
returns to the broker's `/signed-out` (the client's only post-logout redirect
URI), which forwards to the app host. Other hosts' sessions are untouched.

Spec: [app-auth-verifier](../../openspec/specs/app-auth-verifier/spec.md),
[app-auth-broker](../../openspec/specs/app-auth-broker/spec.md),
[app-auth-chart-contract](../../openspec/specs/app-auth-chart-contract/spec.md),
[app-auth-data-model](../../openspec/specs/app-auth-data-model/spec.md),
[app-access-list](../../openspec/specs/app-access-list/spec.md),
[app-studio-access](../../openspec/specs/app-studio-access/spec.md),
[app-oidc-provider](../../openspec/specs/app-oidc-provider/spec.md),
[app-oidc-chart-contract](../../openspec/specs/app-oidc-chart-contract/spec.md) ·
Rationale: [app-authentication](../../openspec/changes/archive/2026-09-28-app-authentication/design.md),
[app-auth-owner-and-preview](../../openspec/changes/archive/2026-10-16-app-auth-owner-and-preview/design.md),
[app-oidc-provider](../../openspec/changes/archive/2026-10-26-app-oidc-provider/design.md)

## Coupling

This service is coupled to three things outside its directory, deliberately and
each with a test that fails when one side moves:

1. **The charts' middlewares** (`templates/app-auth.yaml` in the `custom` and
   `appstudio` charts). Each must list `Cookie` plus exactly `identityHeaders`
   (`request.go`) in `authResponseHeaders`, strip the same set on every route,
   and leave `trustForwardHeader` unset. `api/tests/test_custom_chart.py` and
   `api/tests/test_appstudio_chart.py` read `identityHeaders` out of
   `request.go` and compare.
2. **Traefik's forward-auth behavior**: listed headers are deleted before being
   copied, non-2xx responses reach the browser with `Location` and
   `Set-Cookie`, and relative `Location`s are resolved against the *verifier's*
   address, which is why every redirect here is absolute. `traefik_test.go` runs
   the verifier behind the Traefik version the cluster runs (pinned there;
   bump it with the cluster's) and asserts all of it.
3. **The platform schema.** `store.go` hardwires its queries, and
   `tf/app/caelus/app-auth-bootstrap.sql` grants the `caelus_app_auth` role
   exactly the columns they name. `store_test.go` runs against the migrated test
   database as that role, created by that file.

## Keys

`APP_AUTH_SESSION_KEYS` is `id:base64,id:base64…`, current key first. The first
key seals; all keys open. Rotate by adding a new key in front, and drop the old
one after 7 days (the session lifetime). Replacing a key outright signs every
user out of every app. Values are sealed with AES-256-GCM, with the key derived
per purpose, so a broker flow cookie can never open as a session. The
provider's access tokens are sealed with the same keys.

The provider needs two more, and leaves its routes out unless both are set:

- `APP_AUTH_OIDC_CLIENT_KEYS`, the same format, derives every client secret
  (`api/app/services/app_auth_oidc.py` derives the same values; `client_test.go`
  and the API's test pin one shared vector). The first key derives; all keys
  verify. Rotate by adding a new key in front on both app-auth and the API,
  letting the reconciler republish every SSO deployment's Secret, and dropping
  the old key once every app has restarted with its new secret.
- `APP_AUTH_OIDC_SIGNING_KEYS` is PEM RSA private keys, current first. The first
  signs ID tokens, and the API signs logout tokens with it too;
  `/oidc/jwks` publishes them all, named by their RFC 7638 thumbprint
  (`oidc_test.go` and the API's test pin one shared vector). Rotate by adding
  a key in front on both, and drop the old one after five minutes (the ID
  token lifetime).

Terraform generates all three (`tf/app/app-auth`).

## Running the tests

```bash
cd daemons/app-auth
go test ./...
```

The store tests need `CAELUS_TEST_DATABASE_URL` (set in the devcontainer) and a
migrated database. `traefik_test.go` downloads the pinned Traefik release once,
checks its SHA-256, and caches it; set `TRAEFIK_BIN` to use a local binary,
or `-short` to skip it.

## Releasing

It ships in the shared daemons image; see [`daemons/`](../README.md). It
reaches the cluster only when `app_auth_image` in `tf/app/variables.tf` names a
new version of that image.
