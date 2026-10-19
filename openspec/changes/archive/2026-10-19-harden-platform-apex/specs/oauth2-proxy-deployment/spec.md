## MODIFIED Requirements

### Requirement: oauth2-proxy session is configured
The system SHALL configure oauth2-proxy session handling so the session cookie is scoped **host-only** to the Caelus apex domain (`var.domain`) and is never sent to wildcard user-app subdomains. The cookie SHALL be named `__Host-freepod_platform` and SHALL carry `Secure` and `SameSite=Lax`.

#### Scenario: Session configuration is set
- **WHEN** oauth2-proxy configuration is inspected
- **THEN** `COOKIE_SECRET` references a Kubernetes Secret
- **AND** session type is configured (cookie-based or Redis if high availability)

#### Scenario: Cookie is host-only to the apex domain
- **WHEN** a user completes login and the `Set-Cookie` for `__Host-freepod_platform` is inspected
- **THEN** the cookie has **no** `Domain` attribute (host-only), bound to `${var.domain}`
- **AND** it carries `Path=/`, `Secure`, `HttpOnly` and `SameSite=Lax`
- **AND** `cookie_domains` is not set in the oauth2-proxy configuration

#### Scenario: Chunk and CSRF cookies keep the prefix
- **WHEN** oauth2-proxy splits the session across chunks, or issues its login CSRF cookie
- **THEN** each of those cookies is named with the `__Host-freepod_platform` prefix (`_0`, `_1`, …, `_csrf`)

#### Scenario: Cookie is not sent to user-app subdomains
- **WHEN** the browser issues a request to a deployed user app at `<app>.${var.domain}`
- **THEN** no `__Host-freepod_platform*` cookie is included in the request
