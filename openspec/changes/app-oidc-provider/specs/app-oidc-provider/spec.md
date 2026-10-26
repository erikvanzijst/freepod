# Spec Delta

## ADDED Requirements

### Requirement: One OpenID Provider per environment

The broker SHALL act as an OpenID Provider for tenant apps with issuer `https://login.freepod.eu` in production and `https://login.dev.freepod.eu` in development. It SHALL authenticate users only through its existing identity-provider client, and SHALL serve only its own environment's deployments.

#### Scenario: Cross-environment client

- **WHEN** the production provider receives an authorization request whose `client_id` is a development deployment's ID
- **THEN** it treats the client as unknown

### Requirement: Discovery metadata

The provider SHALL publish OpenID Connect discovery metadata at `<issuer>/.well-known/openid-configuration`. It SHALL name the authorization, token, userinfo, JWKS and end-session endpoints, all on the issuer's host. It SHALL advertise only the `code` response type, the `public` subject type, `RS256` ID token signing, the `client_secret_basic` and `client_secret_post` client authentication methods, and the `S256` code challenge method.

#### Scenario: Discovery

- **WHEN** a client fetches `https://login.freepod.eu/.well-known/openid-configuration`
- **THEN** it receives metadata whose `issuer` is `https://login.freepod.eu` and whose endpoints are all on that host

### Requirement: Every SSO-enabled deployment is a client

A deployment SHALL be a client of the provider exactly when it is not deleted and the release it serves has SSO enabled: the template's system value for `sso.enabled` when the template sets one, otherwise the release's user value, otherwise disabled. Its client ID SHALL be the deployment's ID. No record other than the deployment and its release SHALL be needed for it to be a client, and the identity provider SHALL hold no configuration for it.

#### Scenario: Enabled by the user

- **WHEN** an authorization request names a deployment whose serving release has the user value `sso.enabled: true`
- **THEN** the provider proceeds

#### Scenario: Template value wins

- **WHEN** a deployment's template sets `sso.enabled: false` as a system value and its user values set `sso.enabled: true`
- **THEN** the provider treats the client as unknown

#### Scenario: Not yet rolled out

- **WHEN** a deployment's user values enable SSO but the release it serves does not
- **THEN** the provider treats the client as unknown

#### Scenario: Header authentication alone

- **WHEN** a deployment has `auth.enabled: true` and no `sso.enabled`
- **THEN** the provider treats the client as unknown, and header authentication is unaffected

#### Scenario: Deleted deployment

- **WHEN** a client authenticates at the token endpoint with the credentials of a deployment that has since been deleted
- **THEN** the provider answers `invalid_client`

### Requirement: Client secrets are derived

A client's secret SHALL be derived from its client ID with a per-environment keyring that the platform and the provider share, so that no per-client secret is stored. The provider SHALL accept a secret derived with any key in the keyring, and SHALL compare secrets in constant time. The token endpoint SHALL accept the secret by HTTP Basic authentication or in the form body, and SHALL refuse a request that offers it both ways.

#### Scenario: Correct secret

- **WHEN** a client presents its derived secret at the token endpoint
- **THEN** the client is authenticated

#### Scenario: Another deployment's secret

- **WHEN** a client presents the secret derived for a different deployment
- **THEN** the provider answers `invalid_client`

#### Scenario: Key rotation

- **WHEN** a new key has been added in front of the keyring and a client still presents a secret derived with the previous key
- **THEN** the client is authenticated

### Requirement: Redirect URIs come from the deployment

The provider SHALL accept a redirect URI only when it is an absolute `https` URI without userinfo, fragment or explicit port whose host equals the deployment's hostname case-insensitively, or when it exactly equals one of the URIs in the serving release's template system value `sso.redirectUris`. Redirect URIs SHALL NOT be taken from user values. A request with a redirect URI it does not accept SHALL get an error page and no redirect.

#### Scenario: Own hostname

- **WHEN** the deployment at `photos.alice.freepod.eu` requests `https://photos.alice.freepod.eu/auth/login`
- **THEN** the provider accepts the redirect URI

#### Scenario: Custom domain

- **WHEN** a deployment whose hostname is `photos.example.com` requests `https://photos.example.com/callback`
- **THEN** the provider accepts the redirect URI

#### Scenario: Another host

- **WHEN** a deployment requests `https://evil.example/callback`
- **THEN** the provider shows an error page and does not redirect

#### Scenario: Native client scheme from the template

- **WHEN** a deployment's template lists `app.immich:///oauth-callback` in `sso.redirectUris` and the request names exactly that URI
- **THEN** the provider accepts the redirect URI

#### Scenario: Native scheme from user values

- **WHEN** only the deployment's user values list `app.evil:///steal` under `sso.redirectUris`
- **THEN** the provider shows an error page and does not redirect

#### Scenario: Plain HTTP

- **WHEN** a deployment requests `http://photos.alice.freepod.eu/callback`
- **THEN** the provider shows an error page and does not redirect

### Requirement: Errors before and after validation

Until both the client and the redirect URI of an authorization request are validated, the provider SHALL answer every error with an error page on its own host and SHALL NOT redirect. Once both are validated, it SHALL return errors to the redirect URI as OAuth 2.0 error responses carrying the request's `state`.

#### Scenario: Unknown client

- **WHEN** an authorization request names a client ID that is no SSO-enabled deployment
- **THEN** the provider shows an error page and does not redirect

#### Scenario: Unsupported response type

- **WHEN** an otherwise valid request asks for `response_type=token`
- **THEN** the provider redirects back with `error=unsupported_response_type` and the request's `state`

### Requirement: Authorization code flow

The provider SHALL support only the authorization code flow and SHALL require the `openid` scope. It SHALL authenticate the user through the identity provider, refusing unverified email addresses as the broker does. It SHALL ask for consent under the same rules, records and claims as header authentication, keyed by the user's subject and the deployment. It SHALL then redirect to the validated redirect URI with a code and the request's `state`.

#### Scenario: First sign-in

- **WHEN** a user signs in to an SSO-enabled deployment for the first time
- **THEN** the provider shows the consent page naming the deployment's hostname before issuing a code

#### Scenario: Consent given through header authentication

- **WHEN** a user already consented to a deployment through header authentication and signs in to it through the provider
- **THEN** no consent page is shown

### Requirement: Codes are single-use and bound

A code SHALL be redeemable once, within 60 seconds, by the client it was issued to, with the redirect URI it was issued for. When the authorization request carried a `code_challenge`, its method SHALL be `S256`, any other method SHALL be refused, and redemption SHALL require the matching `code_verifier`.

#### Scenario: Code replay

- **WHEN** a code is redeemed a second time
- **THEN** the provider answers `invalid_grant`

#### Scenario: Code for another client

- **WHEN** a client redeems a code issued to another deployment
- **THEN** the provider answers `invalid_grant`

#### Scenario: Missing verifier

- **WHEN** a code was issued with a `code_challenge` and the token request carries no `code_verifier`
- **THEN** the provider answers `invalid_grant`

#### Scenario: Plain challenge

- **WHEN** an authorization request carries `code_challenge_method=plain`
- **THEN** the provider redirects back with `error=invalid_request`

### Requirement: ID tokens

The token endpoint SHALL return an ID token and an access token, and no refresh token. The ID token SHALL be a JWT signed with RS256 under a key published at the JWKS endpoint and named by `kid`. Its claims SHALL be `iss` (the issuer), `aud` and `azp` (the client ID), `sub` (the user's identity-provider subject), `email`, `email_verified: true`, `name`, `iat`, `auth_time`, `exp` at most 300 seconds after `iat`, and `nonce` when the request carried one.

#### Scenario: Audience

- **WHEN** an ID token issued to one deployment is presented to an app verifying against another deployment's client ID
- **THEN** its audience does not match

#### Scenario: Same subject as headers

- **WHEN** the same user signs in to a header-authenticated app and an SSO-enabled app
- **THEN** the ID token's `sub` equals the `X-Freepod-User` header the first app received

#### Scenario: Signing key rotation

- **WHEN** a new signing key has been added in front of the keyring
- **THEN** new ID tokens are signed with it, and the JWKS endpoint publishes both public keys

### Requirement: Access tokens and userinfo

The access token SHALL be usable only at the userinfo endpoint, for at most one hour. The userinfo endpoint SHALL answer the same `sub`, `email`, `email_verified` and `name` as the ID token. The provider SHALL store no issued token.

#### Scenario: Userinfo

- **WHEN** a client calls the userinfo endpoint with a valid access token
- **THEN** it receives the user's `sub`, `email`, `email_verified` and `name`

#### Scenario: Expired access token

- **WHEN** a client calls the userinfo endpoint with an access token issued more than an hour ago
- **THEN** the provider answers `401` with `error="invalid_token"`

### Requirement: Ending the session

The end-session endpoint SHALL end the user's identity-provider session through the broker's existing sign-out round trip, and then redirect to `post_logout_redirect_uri` when that URI passes the redirect URI rules for the named `client_id`, carrying the request's `state`. Otherwise it SHALL end on the broker's signed-out page.

#### Scenario: Return to the app

- **WHEN** an app sends a user to the end-session endpoint with its own `client_id` and `https://photos.alice.freepod.eu/` as the post-logout redirect
- **THEN** after the identity-provider session ends, the user lands on `https://photos.alice.freepod.eu/`

#### Scenario: Foreign post-logout redirect

- **WHEN** the post-logout redirect is not on the deployment's hostname or its template's list
- **THEN** the user lands on the broker's signed-out page
