## Why

The platform apex and the login host should follow current browser hardening
practice: HTTPS only, a host-bound session cookie, framing refused, and request
bodies parsed only as what they declare. Several of these were missing or, in
the case of the UI's framing headers, configured but never sent.

## What Changes

- **API body parsing:** FastAPI is raised to a release whose
  `strict_content_type` default refuses to parse a request body as JSON when it
  carries no JSON `Content-Type`.
- **API request origin:** the API refuses state-changing requests that a
  browser started from a page on another origin, unless that origin is one of
  its trusted CORS origins.
- **Sign in with Freepod:** the verifier no longer identifies a state-changing
  request or WebSocket handshake that a browser started from a page on another
  origin.
- **App Studio framing:** the studio's Ingress answers with
  `X-Frame-Options: SAMEORIGIN`.
- **Session cookie:** oauth2-proxy's cookie is renamed
  `__Host-freepod_platform` and marked `Secure` and `SameSite=Lax`. The
  `__Host-` prefix binds it to the apex host.
  **BREAKING** (operational): every platform session is invalidated once, and
  users sign in again.
- **HTTPS only on the apex and the login host:** their routes leave the `web`
  entrypoint, so plain HTTP falls through to the cluster's HTTP→HTTPS redirect
  instead of being served.
- **Framing:** every apex route answers with `X-Frame-Options: SAMEORIGIN` and
  `Content-Security-Policy: frame-ancestors 'self'`, set at the edge.
- **Request and response headers:** the UI route forwards no `Cookie` header
  to nginx, which reads none. The shared `websecure` headers middleware removes
  `Clear-Site-Data` from every response.
- **Reserved names:** prod reserves `dev.freepod.eu`, dev's wildcard domain.

## Capabilities

### New Capabilities
- `platform-apex-edge`: what the edge guarantees for the platform apex: HTTPS
  only, framing refused, no cookies forwarded to the UI, and API bodies parsed
  as JSON only when declared so.

### Modified Capabilities
- `oauth2-proxy-deployment`: the session cookie's name, `Secure` and `SameSite`.
- `logout-infrastructure`: scenarios name the renamed cookie.
- `cluster-hsts`: the shared middleware also removes `Clear-Site-Data`.
- `app-auth-verifier`: requests other origins' pages start are not identified.
- `app-studio-access`: only the studio's own origin may frame it.

## Impact

- `api/pyproject.toml`, `api/uv.lock` (FastAPI), one test that walked
  `app.routes`, which FastAPI no longer flattens; `api/app/origin_guard.py`
  and `api/app/main.py`.
- `daemons/app-auth` (verifier), `daemons/VERSION` 0.3.1 and the
  `app_auth_image` pin.
- `products/appstudio/chart` 0.2.13 and its catalog `chart_version`.
- `tf/app/login` (oauth2-proxy config, apex headers Middleware, `/oauth2`
  route), `tf/app/caelus/ingress.tf`, `tf/app/app-auth` (broker route),
  `tf/app/variables.tf` (prod reserved hostnames), `tf/app/main.tf`.
- `tf/deps/system/hsts.tf` (cluster-wide).
- `ui/nginx.conf`: drops server-level headers nginx never sent, because every
  location sets its own `add_header`.
- Users: one forced re-login per environment.
