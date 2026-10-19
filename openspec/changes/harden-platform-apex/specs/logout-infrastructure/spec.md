## MODIFIED Requirements

### Requirement: oauth2-proxy backend logout URL configuration
The oauth2-proxy Helm deployment SHALL include a `--backend-logout-url` flag
set to the `freepod` realm's OIDC `end_session_endpoint` with the `{id_token}`
placeholder:
`https://keycloak.freepod.eu/realms/freepod/protocol/openid-connect/logout?id_token_hint={id_token}`.

#### Scenario: User hits sign_out endpoint
- **WHEN** an authenticated user's browser navigates to `/oauth2/sign_out`
- **THEN** oauth2-proxy makes a server-side HTTP request to Keycloak's logout
  endpoint with the real `id_token` substituted for `{id_token}`
- **AND** Keycloak terminates the user's SSO session
- **AND** oauth2-proxy clears its own `__Host-freepod_platform` session cookie
- **AND** the browser is redirected to the URL specified in the `rd` query
  parameter

#### Scenario: id_token is present in session
- **WHEN** the sign_out request carries a valid `__Host-freepod_platform`
  cookie containing an id_token
- **THEN** the `{id_token}` placeholder in `backend-logout-url` is replaced
  with the actual token value before the server-side call

#### Scenario: Logout targets the realm that issued the session
- **WHEN** the backend logout URL is inspected
- **THEN** its realm path matches the `oidc-issuer-url` realm
- **AND** neither references the `master` realm

### Requirement: Traefik IngressRoute for /oauth2/sign_out on app domain
A Traefik `IngressRoute` CRD SHALL be created in the login namespace that
matches requests to `Host(var.domain) && PathPrefix(/oauth2/sign_out)` and
routes them to the oauth2-proxy service on port 8080. This route SHALL NOT
apply the `forward-auth` or `oauth-errors` middleware.

#### Scenario: Frontend navigates to /oauth2/sign_out on app domain
- **WHEN** a browser navigates to `https://<app-domain>/oauth2/sign_out?rd=...`
- **THEN** Traefik routes the request to the oauth2-proxy service via the
  IngressRoute
- **AND** the request is NOT processed by the forward-auth middleware
- **AND** the request is NOT processed by the oauth-errors middleware

#### Scenario: IngressRoute takes priority over catch-all
- **WHEN** a request matches both the IngressRoute path `/oauth2/sign_out` and
  the Caelus ingress catch-all path `/`
- **THEN** the IngressRoute for `/oauth2/sign_out` takes priority and the
  request reaches oauth2-proxy, not the UI service

#### Scenario: Session cookie is sent on app domain
- **WHEN** the `__Host-freepod_platform` cookie has been issued host-only by
  the apex callback on `<app-domain>`
- **AND** the browser navigates to `https://<app-domain>/oauth2/sign_out`
- **THEN** the cookie is included in the request, allowing oauth2-proxy to read
  the session and extract the id_token
