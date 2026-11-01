# Spec Delta

## ADDED Requirements

### Requirement: Listed deployments admit only their people

For a client whose serving release has `auth.access: listed`, the provider SHALL apply the access list after the user authenticates and before consent, and SHALL issue a code only to the owner or a listed person. A refused user SHALL see the no-access page on the provider's host, or, with `prompt=none`, be redirected back with `error=access_denied`.

#### Scenario: Stranger signs in

- **WHEN** a Freepod account not on the list of a `listed` OIDC deployment completes sign-in at the identity provider
- **THEN** the provider shows the no-access page naming the deployment's address, shows no consent page, and issues no code

#### Scenario: Silent sign-in of a stranger

- **WHEN** a request with `prompt=none` reaches such an account that has a session
- **THEN** the provider redirects back with `error=access_denied` and shows no page

#### Scenario: Listed person

- **WHEN** a listed person signs in to the deployment for the first time
- **THEN** the provider shows the consent page and then issues a code

### Requirement: Access is checked again after the code

The token endpoint and the userinfo endpoint SHALL refuse a user who is no longer the owner or on the list of a `listed` client, even with an unexpired code or access token: the token endpoint with `invalid_grant`, userinfo with `401` and `error="invalid_token"`.

#### Scenario: Removed between code and token

- **WHEN** a listed person's entry is removed after the provider issued them a code and before the client redeems it
- **THEN** the token endpoint answers `invalid_grant`

#### Scenario: Removed while holding an access token

- **WHEN** the client calls userinfo with an unexpired access token for a person since removed from the list
- **THEN** the provider answers `401` with `error="invalid_token"`

### Requirement: Back-channel logout tokens

When access for a subject is revoked on a client that declares `auth.oidc.backchannelLogoutPath`, the platform SHALL POST a logout token as `logout_token` in a form body to `https://<hostname><path>`, reaching the app through the platform's own ingress, without following redirects.

#### Scenario: App refuses the token

- **WHEN** the app answers a logout token with any status other than `2xx`, or cannot be reached
- **THEN** the revocation fails and is not retried

### Requirement: Logout token contents

A logout token SHALL be signed with the provider's current ID token key, with `typ: logout+jwt`. It SHALL carry the provider's issuer as `iss`, the client ID as `aud`, `iat`, `exp` at most 120 seconds later, a unique `jti`, `sub` and the back-channel logout event, and no `nonce` or `sid`.

#### Scenario: Token contents

- **WHEN** the platform sends a logout token for Ana's subject to a client
- **THEN** the token verifies against the JWKS endpoint, its `aud` is the client ID, its `sub` is Ana's subject, and it has the `http://schemas.openid.net/event/backchannel-logout` event and no `nonce`

## MODIFIED Requirements

### Requirement: Discovery metadata

The provider SHALL publish OpenID Connect discovery metadata at `<issuer>/.well-known/openid-configuration`. It SHALL name the authorization, token, userinfo, JWKS and end-session endpoints, all on the issuer's host. It SHALL advertise only the `code` response type, the `public` subject type, `RS256` ID token signing, the `client_secret_basic` and `client_secret_post` client authentication methods, and the `S256` code challenge method. It SHALL advertise `backchannel_logout_supported: true` and `backchannel_logout_session_supported: false`.

#### Scenario: Discovery

- **WHEN** a client fetches `https://login.freepod.eu/.well-known/openid-configuration`
- **THEN** it receives metadata whose `issuer` is `https://login.freepod.eu` and whose endpoints are all on that host

#### Scenario: Back-channel logout advertised

- **WHEN** a client reads the discovery metadata
- **THEN** it says back-channel logout is supported without session IDs

### Requirement: Every SSO-enabled deployment is a client

A deployment SHALL be a client of the provider exactly when it is not deleted, the template of the release it serves declares at least one valid path in the system value `auth.oidc.redirectPaths`, and that release sets both `auth.enabled: true` and `auth.protocol: oidc`: for each key, the release's user value when it sets one, otherwise the template's system value, otherwise the contract's default.

#### Scenario: Enabled by the user

- **WHEN** an authorization request names a deployment whose template declares `auth.oidc.redirectPaths` and `auth.protocol: oidc`, and whose serving release has the user value `auth.enabled: true`
- **THEN** the provider proceeds

#### Scenario: Template does not declare SSO

- **WHEN** a deployment's values set `auth.enabled: true` and `auth.protocol: oidc` but its template declares no `auth.oidc.redirectPaths`
- **THEN** the provider treats the client as unknown

#### Scenario: Enabled by the template

- **WHEN** a deployment's template sets `auth.enabled: true`, `auth.protocol: oidc` and `auth.oidc.redirectPaths` as system values and its user values say nothing about `auth`
- **THEN** the provider proceeds

#### Scenario: User value over the template's default

- **WHEN** a deployment's template sets `auth.enabled: true` as a system value and its user values set `auth.enabled: false`
- **THEN** the provider treats the client as unknown, as the chart renders SSO off

#### Scenario: Not yet rolled out

- **WHEN** a deployment's user values enable SSO but the release it serves does not
- **THEN** the provider treats the client as unknown

#### Scenario: Header authentication alone

- **WHEN** a deployment has `auth.enabled: true` and `auth.protocol` left at `header`
- **THEN** the provider treats the client as unknown, and header authentication is unaffected

#### Scenario: Deleted deployment

- **WHEN** a client authenticates at the token endpoint with the credentials of a deployment that has since been deleted
- **THEN** the provider answers `invalid_client`

### Requirement: Clients need no registration

A client's ID SHALL be its deployment's ID. No record other than the deployment, its release and its template SHALL be needed for it to be a client, and the identity provider SHALL hold no configuration for it.

#### Scenario: New deployment

- **WHEN** a deployment of a template that declares SSO is created with `auth.enabled: true` and `auth.protocol: oidc` and its release is applied
- **THEN** it is a client under its own deployment ID, and nothing changed in the identity provider

### Requirement: Redirect URIs match exactly

The provider SHALL accept a redirect URI only when it equals exactly `https://<the deployment's hostname><path>` for a path in the serving release's template system value `auth.oidc.redirectPaths`, or exactly one of the URIs in the template system value `auth.oidc.nativeRedirectUris`. Redirect URIs SHALL NOT be taken from user values, and no other path, query or host SHALL be accepted. A request with a redirect URI the provider does not accept SHALL get an error page and no redirect.

#### Scenario: Declared callback path

- **WHEN** the template declares `auth.oidc.redirectPaths: ["/oidc/callback"]` and the deployment at `wiki-alice.freepod.app` requests `https://wiki-alice.freepod.app/oidc/callback`
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

The provider SHALL honor an entry of `auth.oidc.redirectPaths`, and the value of `auth.oidc.backchannelLogoutPath`, only when it starts with `/` but not `//`, contains no `?`, `#`, `\` or control character, and the URI formed by joining `https://`, the deployment's hostname and the entry parses with a host equal to the deployment's hostname and no userinfo or port. It SHALL ignore any other entry and log it. A template whose redirect path entries are all ignored SHALL make no clients.

#### Scenario: Userinfo trick

- **WHEN** a template lists `@evil.example/cb` in `auth.oidc.redirectPaths`, and a request names `https://wiki-alice.freepod.app@evil.example/cb`
- **THEN** the provider ignores the entry and shows an error page without redirecting

#### Scenario: Host suffix trick

- **WHEN** a template lists `.evil.example/cb` in `auth.oidc.redirectPaths`, and a request names `https://wiki-alice.freepod.app.evil.example/cb`
- **THEN** the provider ignores the entry and shows an error page without redirecting

#### Scenario: Port trick

- **WHEN** a template lists `:443@evil.example/cb` in `auth.oidc.redirectPaths`
- **THEN** the provider ignores the entry

#### Scenario: Query in a declared path

- **WHEN** a template lists `/oidc/callback?next=/` in `auth.oidc.redirectPaths`
- **THEN** the provider ignores the entry

#### Scenario: No valid path

- **WHEN** every entry of a template's `auth.oidc.redirectPaths` is ignored
- **THEN** the provider treats its deployments as unknown clients

#### Scenario: Logout path off the host

- **WHEN** a template sets `auth.oidc.backchannelLogoutPath: "@evil.example/logout"`
- **THEN** the provider ignores it and sends that template's deployments no logout tokens

### Requirement: Native redirect URIs use private-use schemes

The provider SHALL honor an entry of `auth.oidc.nativeRedirectUris` only when its scheme is neither `http` nor `https` and is in reverse-domain form containing at least one `.`. It SHALL ignore any other entry and log it.

#### Scenario: Mobile app callback

- **WHEN** a template lists `app.immich:///oauth-callback` and the request names exactly that URI
- **THEN** the provider accepts the redirect URI

#### Scenario: HTTPS entry in the native list

- **WHEN** a template lists `https://collector.example/cb` in `auth.oidc.nativeRedirectUris`
- **THEN** the provider ignores the entry and refuses requests naming it

#### Scenario: Native scheme from user values

- **WHEN** only the deployment's user values list `app.evil:///steal` under `auth.oidc.nativeRedirectUris`
- **THEN** the provider shows an error page and does not redirect

### Requirement: PKCE is required

Every authorization request SHALL carry a `code_challenge` with method `S256`, unless the template sets the system value `auth.oidc.pkce: false`. That opt-out SHALL NOT apply to native redirect URIs. Any other method SHALL be refused. A code issued with a challenge SHALL be redeemable only with the matching `code_verifier`, and a token request carrying a `code_verifier` for a code issued without a challenge SHALL be refused.

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

- **WHEN** a template sets `auth.oidc.pkce: false` and a request without a challenge names one of its native redirect URIs
- **THEN** the provider redirects back with `error=invalid_request`

### Requirement: Access tokens and userinfo

The access token SHALL be usable only at the userinfo endpoint, for at most ten minutes. The userinfo endpoint SHALL answer only while the token's client is still an eligible deployment and, for a `listed` client, the token's user is still admitted, with the same `sub`, `email`, `email_verified` and `name` as the ID token. The provider SHALL store no issued token.

#### Scenario: Userinfo

- **WHEN** a client calls the userinfo endpoint with a valid access token
- **THEN** it receives the user's `sub`, `email`, `email_verified` and `name`

#### Scenario: Expired access token

- **WHEN** a client calls the userinfo endpoint with an access token issued more than ten minutes ago
- **THEN** the provider answers `401` with `error="invalid_token"`

#### Scenario: Deployment turned SSO off

- **WHEN** a client calls the userinfo endpoint with an unexpired access token after its deployment stopped being an eligible client
- **THEN** the provider answers `401` with `error="invalid_token"`
