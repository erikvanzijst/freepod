# app-oidc-provider Specification

## Purpose

Defines the OpenID Provider the app authentication broker runs for tenant apps on its login host: which deployments are clients, how they authenticate, which redirect URIs it accepts, the authorization code flow with PKCE, and the tokens, claims and end-session behavior it offers.

## Requirements

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

A deployment SHALL be a client of the provider exactly when it is not deleted, the template of the release it serves declares at least one valid path in the system value `sso.redirectPaths`, and that release has SSO enabled: the release's user value for `sso.enabled` when it sets one, otherwise the template's system value, otherwise disabled.

#### Scenario: Enabled by the user

- **WHEN** an authorization request names a deployment whose template declares `sso.redirectPaths` and whose serving release has the user value `sso.enabled: true`
- **THEN** the provider proceeds

#### Scenario: Template does not declare SSO

- **WHEN** a deployment's user values set `sso.enabled: true` but its template declares no `sso.redirectPaths`
- **THEN** the provider treats the client as unknown

#### Scenario: Enabled by the template

- **WHEN** a deployment's template sets `sso.enabled: true` and `sso.redirectPaths` as system values and its user values say nothing about `sso`
- **THEN** the provider proceeds

#### Scenario: User value over the template's default

- **WHEN** a deployment's template sets `sso.enabled: true` as a system value and its user values set `sso.enabled: false`
- **THEN** the provider treats the client as unknown, as the chart renders SSO off

#### Scenario: Not yet rolled out

- **WHEN** a deployment's user values enable SSO but the release it serves does not
- **THEN** the provider treats the client as unknown

#### Scenario: Header authentication alone

- **WHEN** a deployment has `auth.enabled: true` and no `sso.enabled`
- **THEN** the provider treats the client as unknown, and header authentication is unaffected

#### Scenario: Deleted deployment

- **WHEN** a client authenticates at the token endpoint with the credentials of a deployment that has since been deleted
- **THEN** the provider answers `invalid_client`

### Requirement: Clients need no registration

A client's ID SHALL be its deployment's ID. No record other than the deployment, its release and its template SHALL be needed for it to be a client, and the identity provider SHALL hold no configuration for it.

#### Scenario: New deployment

- **WHEN** a deployment of a template that declares SSO is created with `sso.enabled: true` and its release is applied
- **THEN** it is a client under its own deployment ID, and nothing changed in the identity provider

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

### Requirement: Redirect URIs match exactly

The provider SHALL accept a redirect URI only when it equals exactly `https://<the deployment's hostname><path>` for a path in the serving release's template system value `sso.redirectPaths`, or exactly one of the URIs in the template system value `sso.nativeRedirectUris`. Redirect URIs SHALL NOT be taken from user values, and no other path, query or host SHALL be accepted. A request with a redirect URI the provider does not accept SHALL get an error page and no redirect.

#### Scenario: Declared callback path

- **WHEN** the template declares `sso.redirectPaths: ["/oidc/callback"]` and the deployment at `wiki-alice.freepod.app` requests `https://wiki-alice.freepod.app/oidc/callback`
- **THEN** the provider accepts the redirect URI

#### Scenario: Custom domain

- **WHEN** a deployment whose hostname is `wiki.example.com` requests `https://wiki.example.com/oidc/callback` and the template declares that path
- **THEN** the provider accepts the redirect URI

#### Scenario: Another path on the same host

- **WHEN** the deployment at `wiki-alice.freepod.app` requests `https://wiki-alice.freepod.app/shared/page`
- **THEN** the provider shows an error page and does not redirect

#### Scenario: Extra query

- **WHEN** a deployment requests `https://wiki-alice.freepod.app/oidc/callback?code=ATTACKER`
- **THEN** the provider shows an error page and does not redirect

#### Scenario: Another host

- **WHEN** a deployment requests `https://evil.example/oidc/callback`
- **THEN** the provider shows an error page and does not redirect

#### Scenario: Plain HTTP

- **WHEN** a deployment requests `http://wiki-alice.freepod.app/oidc/callback`
- **THEN** the provider shows an error page and does not redirect

### Requirement: Callback paths cannot leave the deployment's host

The provider SHALL honor an entry of `sso.redirectPaths` only when it starts with `/` but not `//`, contains no `?`, `#`, `\` or control character, and the URI formed by joining `https://`, the deployment's hostname and the entry parses with a host equal to the deployment's hostname and no userinfo or port. It SHALL ignore any other entry and log it. A template whose entries are all ignored SHALL make no clients.

#### Scenario: Userinfo trick

- **WHEN** a template lists `@evil.example/cb` in `sso.redirectPaths`, and a request names `https://wiki-alice.freepod.app@evil.example/cb`
- **THEN** the provider ignores the entry and shows an error page without redirecting

#### Scenario: Host suffix trick

- **WHEN** a template lists `.evil.example/cb` in `sso.redirectPaths`, and a request names `https://wiki-alice.freepod.app.evil.example/cb`
- **THEN** the provider ignores the entry and shows an error page without redirecting

#### Scenario: Port trick

- **WHEN** a template lists `:443@evil.example/cb` in `sso.redirectPaths`
- **THEN** the provider ignores the entry

#### Scenario: Query in a declared path

- **WHEN** a template lists `/oidc/callback?next=/` in `sso.redirectPaths`
- **THEN** the provider ignores the entry

#### Scenario: No valid path

- **WHEN** every entry of a template's `sso.redirectPaths` is ignored
- **THEN** the provider treats its deployments as unknown clients

### Requirement: Native redirect URIs use private-use schemes

The provider SHALL honor an entry of `sso.nativeRedirectUris` only when its scheme is neither `http` nor `https` and is in reverse-domain form containing at least one `.`. It SHALL ignore any other entry and log it.

#### Scenario: Mobile app callback

- **WHEN** a template lists `app.immich:///oauth-callback` and the request names exactly that URI
- **THEN** the provider accepts the redirect URI

#### Scenario: HTTPS entry in the native list

- **WHEN** a template lists `https://collector.example/cb` in `sso.nativeRedirectUris`
- **THEN** the provider ignores the entry and refuses requests naming it

#### Scenario: Native scheme from user values

- **WHEN** only the deployment's user values list `app.evil:///steal` under `sso.nativeRedirectUris`
- **THEN** the provider shows an error page and does not redirect

### Requirement: Errors before and after validation

Until both the client and the redirect URI of an authorization request are validated, the provider SHALL answer every error with an error page on its own host and SHALL NOT redirect. Once both are validated, it SHALL return errors to the redirect URI as OAuth 2.0 error responses carrying the request's `state`.

#### Scenario: Unknown client

- **WHEN** an authorization request names a client ID that is no SSO-enabled deployment
- **THEN** the provider shows an error page and does not redirect

#### Scenario: Unsupported response type

- **WHEN** an otherwise valid request asks for `response_type=token`
- **THEN** the provider redirects back with `error=unsupported_response_type` and the request's `state`

### Requirement: Request parameters are bounded

The provider SHALL refuse an authorization request whose `state` exceeds 512 bytes, whose `nonce` exceeds 256 bytes, whose `redirect_uri` exceeds 2048 bytes, or whose `code_challenge`, when present, is not 43 characters. It SHALL do so before setting any cookie.

#### Scenario: Oversized state

- **WHEN** an authorization request with a valid client and redirect URI carries a 4 KB `state`
- **THEN** the provider answers `invalid_request` and sets no cookie

### Requirement: Authorization code flow

The provider SHALL support only the authorization code flow and SHALL require the `openid` scope. It SHALL accept the authorization request as an HTTP GET with its parameters in the query, and as an HTTP POST with them in a form body, under the same rules. It SHALL authenticate the user through the identity provider, refusing unverified email addresses as the broker does, and passing `prompt` and `max_age` through. It SHALL ask for consent under the same rules, records and claims as header authentication, keyed by the user's subject and the deployment. It SHALL then redirect to the validated redirect URI with a code and the request's `state`.

#### Scenario: First sign-in

- **WHEN** a user signs in to an SSO-enabled deployment for the first time
- **THEN** the provider shows the consent page naming the deployment's hostname before issuing a code

#### Scenario: Consent given through header authentication

- **WHEN** a user already consented to a deployment through header authentication and signs in to it through the provider
- **THEN** no consent page is shown

#### Scenario: Authorization request by POST

- **WHEN** an app sends the authorization request as a form POST
- **THEN** the provider handles it exactly as the same request by GET

#### Scenario: Silent sign-in without consent

- **WHEN** a request with `prompt=none` reaches a user who has a session but has not consented to the deployment
- **THEN** the provider redirects back with `error=consent_required` and shows no page

#### Scenario: Consent redirect to a native app

- **WHEN** a user consents during a sign-in whose redirect URI is `app.immich:///oauth-callback`
- **THEN** the consent response's content security policy allows the `app.immich:` scheme as a form action, and the redirect reaches the app

### Requirement: PKCE is required

Every authorization request SHALL carry a `code_challenge` with method `S256`, unless the template sets the system value `sso.pkce: false`. That opt-out SHALL NOT apply to native redirect URIs. Any other method SHALL be refused. A code issued with a challenge SHALL be redeemable only with the matching `code_verifier`, and a token request carrying a `code_verifier` for a code issued without a challenge SHALL be refused.

#### Scenario: Missing challenge

- **WHEN** a request for a template without the opt-out carries no `code_challenge`
- **THEN** the provider redirects back with `error=invalid_request`

#### Scenario: Plain challenge

- **WHEN** an authorization request carries `code_challenge_method=plain`
- **THEN** the provider redirects back with `error=invalid_request`

#### Scenario: Missing verifier

- **WHEN** a code was issued with a `code_challenge` and the token request carries no `code_verifier`
- **THEN** the provider answers `invalid_grant`

#### Scenario: Downgrade

- **WHEN** a code was issued without a challenge under the template's opt-out, and the token request carries a `code_verifier`
- **THEN** the provider answers `invalid_grant`

#### Scenario: Native redirect without PKCE

- **WHEN** a template sets `sso.pkce: false` and a request without a challenge names one of its native redirect URIs
- **THEN** the provider redirects back with `error=invalid_request`

### Requirement: Codes are single-use and bound

A code SHALL be redeemable once, within 60 seconds, by the client it was issued to, with the redirect URI it was issued for.

#### Scenario: Code replay

- **WHEN** a code is redeemed a second time
- **THEN** the provider answers `invalid_grant`

#### Scenario: Code for another client

- **WHEN** a client redeems a code issued to another deployment
- **THEN** the provider answers `invalid_grant`

### Requirement: ID tokens

The ID token SHALL be a JWT with `typ: JWT`, signed with RS256 under a key published at the JWKS endpoint and named by `kid`. Its claims SHALL be `iss` (the issuer), `aud` and `azp` (the client ID), `sub` (the user's identity-provider subject), `email`, `email_verified: true`, `name`, `iat`, `auth_time` (from the identity provider), `exp` at most 300 seconds after `iat`, and `nonce` when the request carried one.

#### Scenario: Audience

- **WHEN** an ID token issued to one deployment is presented to an app verifying against another deployment's client ID
- **THEN** its audience does not match

#### Scenario: Same subject as headers

- **WHEN** the same user signs in to a header-authenticated app and an SSO-enabled app
- **THEN** the ID token's `sub` equals the `X-Freepod-User` header the first app received

#### Scenario: Signing key rotation

- **WHEN** a new signing key has been added in front of the keyring
- **THEN** new ID tokens are signed with it, and the JWKS endpoint publishes both public keys

### Requirement: No refresh tokens and no username

The token endpoint SHALL return an ID token and an access token, and no refresh token. No token SHALL carry `preferred_username`.

#### Scenario: Token response

- **WHEN** a client redeems a code
- **THEN** the response holds an ID token and an access token, and neither a refresh token nor a username

### Requirement: Access tokens and userinfo

The access token SHALL be usable only at the userinfo endpoint, for at most ten minutes. The userinfo endpoint SHALL answer only while the token's client is still an eligible deployment, with the same `sub`, `email`, `email_verified` and `name` as the ID token. The provider SHALL store no issued token.

#### Scenario: Userinfo

- **WHEN** a client calls the userinfo endpoint with a valid access token
- **THEN** it receives the user's `sub`, `email`, `email_verified` and `name`

#### Scenario: Expired access token

- **WHEN** a client calls the userinfo endpoint with an access token issued more than ten minutes ago
- **THEN** the provider answers `401` with `error="invalid_token"`

#### Scenario: Deployment turned SSO off

- **WHEN** a client calls the userinfo endpoint with an unexpired access token after its deployment stopped being an eligible client
- **THEN** the provider answers `401` with `error="invalid_token"`

### Requirement: Ending the session

The end-session endpoint SHALL end the user's identity-provider session through the broker's existing sign-out round trip. It SHALL then redirect to `post_logout_redirect_uri`, carrying the request's `state`, only when `id_token_hint` is an ID token the provider signed whose `aud` equals `client_id`, its expiry aside, and the URI is the deployment's `https://<hostname>/` or passes the redirect URI rules. Otherwise it SHALL end on the broker's signed-out page.

#### Scenario: Return to the app

- **WHEN** an app sends a user to the end-session endpoint with its own `client_id`, an ID token it received, and `https://wiki-alice.freepod.app/` as the post-logout redirect
- **THEN** after the identity-provider session ends, the user lands on `https://wiki-alice.freepod.app/`

#### Scenario: Missing or foreign hint

- **WHEN** the request has no `id_token_hint`, or one whose audience is another deployment
- **THEN** the user lands on the broker's signed-out page

#### Scenario: Foreign post-logout redirect

- **WHEN** the post-logout redirect is neither the deployment's root nor a declared redirect URI
- **THEN** the user lands on the broker's signed-out page
