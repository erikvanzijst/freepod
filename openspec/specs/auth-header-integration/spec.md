# auth-header-integration Specification

## Purpose
Ensure the identity headers, X-Auth-Request-Email and X-Auth-Request-User, are properly forwarded from oauth2-proxy to Caelus.

## Requirements

### Requirement: oauth2-proxy injects X-Auth-Request-Email header
The system SHALL configure oauth2-proxy to set the X-Auth-Request-Email header
with authenticated user email, whether the request was authenticated by the
oauth2-proxy session cookie or by a verified bearer token. The upstream
application SHALL NOT be able to tell the two apart, so that token support
requires no application change.

#### Scenario: X-Auth-Request-Email header is set
- **WHEN** oauth2-proxy configuration includes `SET_XAUTHREQUEST=1`
- **AND** `SET_XAUTHREQUEST` is enabled
- **THEN** the header `X-Auth-Request-Email` is present in requests to upstream

#### Scenario: Header is set from a cookie session
- **WHEN** a request is authenticated by the oauth2-proxy session cookie
- **THEN** `X-Auth-Request-Email` carries the session's email

#### Scenario: Header is set from a bearer token
- **WHEN** a request is authenticated by a verified bearer token
- **THEN** `X-Auth-Request-Email` carries the token's `email` claim
- **AND** its form is indistinguishable from the cookie-authenticated case

### Requirement: oauth2-proxy preserves existing headers
The system SHALL configure oauth2-proxy to pass through existing X-Auth-Request headers.

#### Scenario: X-Auth-Request headers are preserved
- **WHEN** oauth2-proxy configuration is checked
- **THEN** the option to pass through auth request headers is enabled

### Requirement: Caelus receives X-Auth-Request-Email header
The system SHALL ensure Caelus backend receives the X-Auth-Request-Email header,
and that the value is always one the edge determined. A value supplied by the
client SHALL NOT reach the application on any route that the edge authenticates.

#### Scenario: Backend receives email header
- **WHEN** a request is made through oauth2-proxy to Caelus
- **THEN** the `X-Auth-Request-Email` header is present in the request to the
  upstream service

#### Scenario: A client-supplied identity header is overwritten
- **WHEN** a client sends a request to an authenticated route carrying its own
  `X-Auth-Request-Email` header
- **THEN** the value that reaches the application is the one derived from the
  session or the verified token, not the client's
- **AND** this holds whether the request was authenticated by cookie or by
  bearer token

#### Scenario: Skipped routes remain outside this guarantee
- **WHEN** a request is matched by an oauth2-proxy `skip_auth_routes` rule
- **THEN** oauth2-proxy neither injects nor strips `X-Auth-Request-Email`
- **AND** no endpoint matched by such a rule uses the header for authorization

### Requirement: Email claim maps correctly from Keycloak
The system SHALL ensure the email from Keycloak OIDC claim maps to the X-Auth-Request-Email header.

#### Scenario: Email claim is extracted
- **WHEN** oauth2-proxy is configured
- **THEN** the OIDC claim `email` is mapped to header `X-Auth-Request-Email`

### Requirement: Unauthenticated requests are redirected
The system SHALL redirect unauthenticated users to Keycloak login.

#### Scenario: Unauthenticated request triggers redirect
- **WHEN** a user accesses Caelus without a session
- **THEN** they are redirected to Keycloak authorization endpoint

### Requirement: Authenticated requests pass through
The system SHALL allow authenticated requests to pass through to Caelus.

#### Scenario: Authenticated request passes
- **WHEN** a user with valid OAuth token accesses Caelus
- **THEN** the request reaches Caelus with X-Auth-Request-Email header

### Requirement: Session cookie is handled correctly
The system SHALL configure oauth2-proxy cookie settings for secure operation.

#### Scenario: Cookie settings are secure
- **WHEN** oauth2-proxy configuration is checked
- **THEN** `COOKIE_SECURE` is set appropriately for the environment
- **AND** `COOKIE_DOMAIN` is configured if needed

### Requirement: Caelus Ingress routes through oauth2-proxy
The system SHALL configure the Caelus Ingress to route through oauth2-proxy.

#### Scenario: Caelus Ingress uses oauth2-proxy
- **WHEN** Kubernetes Ingress for Caelus is inspected
- **THEN** the backend service points to oauth2-proxy

### Requirement: forward-auth forwards the Authorization request header

The system SHALL configure the Traefik `forward-auth` middleware to include
`Authorization` among the request headers it copies to oauth2-proxy's auth
endpoint. Without it a bearer token never reaches the component that verifies
it, and every other part of token authentication is inert.

#### Scenario: Authorization is among the forwarded request headers

- **WHEN** the `forward-auth` middleware definition is inspected
- **THEN** its forwarded request headers include both `Cookie` and
  `Authorization`

#### Scenario: A bearer token reaches the verifier

- **WHEN** a client sends a request to a protected route with an
  `Authorization: Bearer` header
- **THEN** oauth2-proxy receives that header on the auth sub-request
- **AND** it is able to verify the token and return an authentication decision

### Requirement: The raw bearer token does not leak past the edge

The system SHALL ensure that whether the upstream application receives an
`Authorization` header is determined by the edge rather than by the client. The
application authenticates on `X-Auth-Request-Email` and has no use for the
token, so the edge SHALL NOT pass a client-supplied `Authorization` header
through unexamined.

#### Scenario: Upstream authorization is edge-controlled

- **WHEN** a bearer-authenticated request reaches the upstream application
- **THEN** any `Authorization` header it carries is the one determined by the
  forward-auth response, not the raw header the client sent

#### Scenario: The application does not authenticate on the token

- **WHEN** the API receives a request
- **THEN** it derives the caller solely from `X-Auth-Request-Email`
- **AND** it does not inspect the `Authorization` header

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
