## ADDED Requirements

### Requirement: The edge forwards the Keycloak subject

The system MUST forward the authenticated identity's Keycloak subject to the upstream
application as `X-Auth-Request-User`, whether the request was authenticated by the
oauth2-proxy session cookie or by a verified bearer token. The two cases MUST be
indistinguishable upstream, for the same reason the email header is: a client should not be
able to change which identity the application sees by changing how it authenticates.

This header is what the application resolves callers by, so the configuration that produces
it — the flag that emits the `X-Auth-Request` set, and the forward-auth middleware's
inclusion of this header among the ones it copies from the auth response — MUST be treated
as load-bearing and MUST NOT be removed as unused.

#### Scenario: The subject header is present on an authenticated request

- **WHEN** a request is authenticated at the edge
- **THEN** `X-Auth-Request-User` is present in the request to the upstream
- **AND** its value is the identity's Keycloak subject

#### Scenario: The header is the same for cookie and bearer authentication

- **WHEN** the same identity authenticates once by session cookie and once by verified
  bearer token
- **THEN** `X-Auth-Request-User` carries the same value in both cases

### Requirement: The subject header is edge-determined

The system MUST ensure the `X-Auth-Request-User` value that reaches the application is the
one the edge derived, on every route the edge authenticates. A value supplied by the client
MUST NOT reach the application on such a route.

Because the application resolves callers by this header, a client-supplied value that
reached it unexamined would be an impersonation of any account, not merely a misleading
label.

#### Scenario: A client-supplied subject header is overwritten

- **WHEN** a client sends a request to an authenticated route carrying its own
  `X-Auth-Request-User` header
- **THEN** the value that reaches the application is the one derived from the session or the
  verified token, not the client's
- **AND** this holds whether the request was authenticated by cookie or by bearer token

#### Scenario: Skipped routes remain outside this guarantee

- **WHEN** a request is matched by an oauth2-proxy `skip_auth_routes` rule
- **THEN** the edge neither injects nor strips `X-Auth-Request-User`
- **AND** no endpoint matched by such a rule uses the header to identify a caller
