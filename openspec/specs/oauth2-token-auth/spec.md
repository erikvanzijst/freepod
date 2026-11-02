# oauth2-token-auth Specification

## Purpose
Let software that is not a browser — command-line tools, scripts and third-party
integrations — authenticate to the Freepod API with an OAuth 2.0 access token
obtained from Keycloak, instead of the browser session cookie that is the only
credential the edge accepts today. Defines the public clients such software
authenticates against, the grants available to it, the audience claim that makes
its token verifiable at the edge, and the error contract it can rely on.
## Requirements
### Requirement: Public CLI clients exist per environment

The system SHALL provide one public Keycloak client per Freepod environment for
use by non-browser clients: `freepod-cli-prod` for `freepod.eu` and
`freepod-cli-dev` for `dev.freepod.eu`. These clients SHALL be public — holding
no client secret — because a client distributed to end users cannot keep one.

A single client SHALL NOT serve both environments, so that a token issued for
one environment is not accepted by the other.

#### Scenario: Both CLI clients exist and are public

- **WHEN** Keycloak clients are listed for realm `freepod`
- **THEN** clients with client IDs `freepod-cli-prod` and `freepod-cli-dev`
  exist
- **AND** each has `publicClient` set to `true`
- **AND** neither has a client secret

#### Scenario: PKCE is mandatory

- **WHEN** either CLI client is inspected
- **THEN** PKCE is required with challenge method `S256`
- **AND** an authorization request that omits `code_challenge` is rejected by
  Keycloak

#### Scenario: The password grant is not available

- **WHEN** either CLI client is inspected
- **THEN** `directAccessGrantsEnabled` is `false`, so a client cannot trade a
  username and password directly for tokens
- **AND** `serviceAccountsEnabled` is `false`

### Requirement: Interactive clients authenticate over a loopback redirect

The system SHALL accept the authorization code grant with PKCE for clients that
can open a browser, using a redirect to an HTTP listener on the loopback
interface. Loopback redirect URIs SHALL be registered without a port, so that a
client binding an ephemeral port matches the registration.

Clients SHALL direct the user to the Keycloak authorization endpoint. The
oauth2-proxy `/oauth2/start` endpoint SHALL NOT be used for this purpose,
because it initiates a browser cookie session rather than issuing tokens to a
client.

#### Scenario: Loopback redirect URIs are registered port-less

- **WHEN** either CLI client's valid redirect URIs are inspected
- **THEN** they include a port-less `http://127.0.0.1` form and a port-less
  `http://localhost` form
- **AND** the registered path is a fixed, non-wildcard callback path

#### Scenario: An ephemeral local port is accepted

- **WHEN** a client binds an arbitrary high-numbered port on `127.0.0.1` and
  requests authorization with that port in its `redirect_uri`
- **THEN** Keycloak accepts the redirect URI
- **AND** the browser is redirected back to that port with an authorization code

#### Scenario: A non-loopback redirect is refused

- **WHEN** a client requests authorization with a `redirect_uri` whose host is
  not a loopback address
- **THEN** Keycloak refuses the request with an invalid redirect URI error
- **AND** no authorization code is issued

#### Scenario: The code cannot be redeemed without the verifier

- **WHEN** an authorization code obtained through this flow is presented at the
  token endpoint with a `code_verifier` that does not match the original
  challenge
- **THEN** the token request is rejected
- **AND** no access or refresh token is issued

### Requirement: Headless clients authenticate with the device authorization grant

The system SHALL enable the OAuth 2.0 Device Authorization Grant on both CLI
clients, so that a client running without a local browser — over SSH, in a
container, or on a headless host — can authenticate by displaying a verification
URL and a user code for the user to complete on a separate device.

This grant SHALL be the supported headless flow. The out-of-band redirect
`urn:ietf:wg:oauth:2.0:oob`, under which a user copies an authorization code
back into the client, SHALL NOT be used: it is removed from current Keycloak
releases, and it exposes a live authorization code through the terminal and
clipboard.

#### Scenario: The device grant is enabled

- **WHEN** either CLI client is inspected
- **THEN** the OAuth 2.0 Device Authorization Grant is enabled

#### Scenario: A headless client obtains tokens without a local browser

- **WHEN** a client posts to the realm's device authorization endpoint with its
  client ID
- **THEN** it receives a device code, a user code and a verification URI
- **AND** after the user completes authentication at that URI, polling the token
  endpoint with the device code returns an access token and a refresh token

#### Scenario: Polling before approval does not yield a token

- **WHEN** a client polls the token endpoint with a device code the user has not
  yet approved
- **THEN** the response is an `authorization_pending` error
- **AND** no token is issued

#### Scenario: The device request requires a PKCE challenge

- **WHEN** a client posts to the device authorization endpoint without
  `code_challenge` and `code_challenge_method`
- **THEN** the request is refused with `invalid_request` and
  `Missing parameter: code_challenge_method`
- **AND** supplying them succeeds, so a device-flow client must perform PKCE and
  present the `code_verifier` when polling the token endpoint, even though the
  device grant has no redirect

#### Scenario: No out-of-band redirect is registered

- **WHEN** either CLI client's valid redirect URIs are inspected
- **THEN** `urn:ietf:wg:oauth:2.0:oob` is not among them

### Requirement: Access tokens carry an audience the edge accepts

The system SHALL assign each CLI client a client scope whose audience protocol
mapper adds that environment's oauth2-proxy client ID to the `aud` claim of
issued access tokens: `freepod-prod` for `freepod-cli-prod` and `freepod-dev`
for `freepod-cli-dev`.

This is required because a Keycloak access token otherwise carries
`aud: ["account"]` and identifies the requesting client only in `azp`, which
does not satisfy the audience verification performed at the edge.

The audience SHALL identify a single environment. A token whose audience names
one environment SHALL NOT be accepted by the other.

#### Scenario: The audience scope is assigned by default

- **WHEN** the client scopes of `freepod-cli-prod` are inspected
- **THEN** a client scope carrying an audience mapper for `freepod-prod` is
  assigned as a default scope
- **WHEN** the client scopes of `freepod-cli-dev` are inspected
- **THEN** a client scope carrying an audience mapper for `freepod-dev` is
  assigned as a default scope

#### Scenario: An issued access token names the environment audience

- **WHEN** an access token obtained through either CLI client is decoded
- **THEN** its `aud` claim contains that environment's oauth2-proxy client ID

#### Scenario: A token is not valid across environments

- **WHEN** an access token issued to `freepod-cli-dev` is presented to
  `freepod.eu`
- **THEN** the request is rejected as unauthenticated, because audience
  verification fails

### Requirement: Access tokens carry the claims the edge authorizes on

The system SHALL assign the CLI clients the client scopes that carry the
identity and membership claims the edge depends on, so that a bearer-
authenticated request is authorized on the same evidence as a browser session.

#### Scenario: Email claim is present

- **WHEN** an access token obtained through either CLI client is decoded
- **THEN** it carries an `email` claim

#### Scenario: Groups claim is present

- **WHEN** an access token obtained through either CLI client is decoded
- **THEN** it carries a `groups` claim with bare group names
- **AND** the claim is present in the access token, not only in the ID token or
  userinfo response

#### Scenario: Subject claim is present

- **WHEN** an access token obtained through either CLI client is decoded
- **THEN** it carries a `sub` claim
- **AND** a bearer-authenticated request reaches the API with that subject as
  the caller's identity, exactly as a browser session for the same user does

### Requirement: Clients can obtain a durable credential

The system SHALL make the `offline_access` scope available to the CLI clients,
so that a client can store a refresh token that survives the SSO session idle
timeout and continue to obtain access tokens without re-prompting the user.

#### Scenario: Offline access is requestable

- **WHEN** a client includes `offline_access` in its authorization or device
  request
- **THEN** the issued refresh token is an offline token
- **AND** it remains usable after the interactive SSO session has ended

#### Scenario: Access tokens are short-lived and refreshable

- **WHEN** an access token expires
- **THEN** the client can obtain a new access token by presenting the refresh
  token at the token endpoint
- **AND** no user interaction is required

### Requirement: Token errors are machine-readable

The system SHALL respond to a request bearing an absent, malformed, expired or
unverifiable token with a machine-readable HTTP status rather than an HTML login
page, so that a non-browser client can distinguish the cases without parsing
markup.

#### Scenario: An invalid token is refused without a redirect

- **WHEN** a request carries an `Authorization: Bearer` header whose token fails
  verification
- **THEN** the response status is `403`
- **AND** the response is not a redirect to the Keycloak login page

#### Scenario: An expired token is refused

- **WHEN** a request carries a well-formed access token whose expiry has passed
- **THEN** the request is refused
- **AND** the client can recover by refreshing and retrying

#### Scenario: A request with no credential is refused

- **WHEN** a request to a protected route carries neither a session cookie nor
  an `Authorization` header
- **THEN** the request is refused with a `401`, matching the behavior the SPA
  already depends on

#### Scenario: An authorization failure is not distinguishable from anonymity

- **WHEN** a valid, correctly-audienced token is presented by a user who is not
  permitted on that environment, such as a non-member of `freepod-dev` on
  `dev.freepod.eu`
- **THEN** the response is `401`, the same status as presenting no credential
- **AND** a client MUST NOT infer from `401` alone that re-authentication will
  help, because re-authenticating succeeds and changes nothing
- **AND** only `403` indicates a token that failed verification and is therefore
  worth refreshing or re-obtaining

### Requirement: Token authentication grants no more than a browser session

The system SHALL treat a bearer-authenticated request as equivalent in privilege
to a browser session for the same user. Access tokens SHALL NOT be presented as
carrying narrower authority, because the API authorizes on user identity alone
and has no notion of OAuth scopes.

#### Scenario: Authorization is identical to a session

- **WHEN** the same user acts through a bearer token and through a browser
  session
- **THEN** both are authorized for exactly the same set of operations

#### Scenario: Revocation is available to the user

- **WHEN** a user wants to invalidate a credential issued to a CLI client
- **THEN** the Keycloak account console lists the client's offline session
- **AND** revoking it there prevents further token refresh
