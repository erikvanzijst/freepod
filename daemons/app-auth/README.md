# app-auth — "Sign in with Freepod" for tenant apps

A `custom` deployment that sets `auth.enabled` gets verified identity headers
(`X-Freepod-User`, `X-Freepod-Email`, `X-Freepod-Name`) on every request, with
Freepod's Keycloak as the identity provider. This service is both halves:

- **The verifier** (`:8080/verify`) is Traefik's forward-auth endpoint for
  every auth-enabled app. It checks a host-bound session cookie, strips it and
  every platform cookie from the request, and sets the identity headers, or
  answers with a redirect to sign in (navigations) or `401` (everything else).
  It also serves `/.freepod/auth/{login,callback,logout}` on each app host,
  from inside forward-auth. The per-request path touches no database.
- **The broker** (`:8081`, public at `login.<domain>`) is the only party that
  talks OIDC to Keycloak, through one client per environment
  (`freepod-apps-{prod,dev}`) with one redirect URI. It checks that the host is
  an auth-enabled deployment, asks for consent once per user and deployment,
  and hands the app host a single-use code bound to that host and to the
  browser that started signing in.

**Logout** (`/.freepod/auth/logout?rd=…`) clears the app host's session, then
goes through the broker's `/logout` to Keycloak's end-session endpoint, so the
next sign-in asks for credentials and can pick another account. Keycloak
returns to the broker's `/signed-out` (the client's only post-logout redirect
URI), which forwards to the app host. Other hosts' sessions are untouched.

Spec: [app-auth-verifier](../../openspec/specs/app-auth-verifier/spec.md),
[app-auth-broker](../../openspec/specs/app-auth-broker/spec.md),
[app-auth-chart-contract](../../openspec/specs/app-auth-chart-contract/spec.md),
[app-auth-data-model](../../openspec/specs/app-auth-data-model/spec.md) ·
Rationale: [app-authentication](../../openspec/changes/archive/2026-09-28-app-authentication/design.md)

## Coupling

This service is coupled to three things outside its directory, deliberately and
each with a test that fails when one side moves:

1. **The `custom` chart's middlewares** (`products/custom/chart/templates/app-auth.yaml`).
   The chart must list `Cookie` plus exactly `identityHeaders` (`request.go`) in
   `authResponseHeaders`, strip the same set on every deployment, and leave
   `trustForwardHeader` unset. `api/tests/test_custom_chart.py` reads
   `identityHeaders` out of `request.go` and compares.
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
per purpose, so a broker flow cookie can never open as a session.

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
