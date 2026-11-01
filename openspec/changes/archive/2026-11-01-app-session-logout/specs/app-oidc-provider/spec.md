# Spec Delta

## ADDED Requirements

### Requirement: Session IDs are per client and per browser

The `sid` the provider gives a client SHALL be derived from the identity provider session and the client ID with a key only app authentication holds. Sign-ins from one identity provider session to one client SHALL receive the same `sid`. Different clients, or different identity provider sessions, SHALL receive different values, and no client SHALL receive the identity provider's own session ID.

#### Scenario: Signing in twice in one browser

- **WHEN** a user signs in to Immich twice in the same browser without signing out
- **THEN** both ID tokens carry the same `sid`

#### Scenario: Two apps

- **WHEN** a user signs in to two deployments in the same browser
- **THEN** their ID tokens carry different `sid` values, and neither equals the identity provider's session ID

#### Scenario: Phone and laptop

- **WHEN** a user signs in to Immich on their laptop and on their phone
- **THEN** the two ID tokens carry different `sid` values

## MODIFIED Requirements

### Requirement: Discovery metadata

The provider SHALL publish OpenID Connect discovery metadata at `<issuer>/.well-known/openid-configuration`. It SHALL name the authorization, token, userinfo, JWKS and end-session endpoints, all on the issuer's host. It SHALL advertise only the `code` response type, the `public` subject type, `RS256` ID token signing, the `client_secret_basic` and `client_secret_post` client authentication methods, and the `S256` code challenge method. It SHALL advertise `backchannel_logout_supported: true` and `backchannel_logout_session_supported: true`.

#### Scenario: Discovery

- **WHEN** a client fetches `https://login.freepod.eu/.well-known/openid-configuration`
- **THEN** it receives metadata whose `issuer` is `https://login.freepod.eu` and whose endpoints are all on that host

#### Scenario: Back-channel logout advertised

- **WHEN** a client reads the discovery metadata
- **THEN** it says back-channel logout is supported with session IDs

### Requirement: ID tokens

The ID token SHALL be a JWT with `typ: JWT`, signed with RS256 under a key published at the JWKS endpoint and named by `kid`. Its claims SHALL be `iss` (the issuer), `aud` and `azp` (the client ID), `sub` (the user's identity-provider subject), `sid` (the user's session at this client), `email`, `email_verified: true`, `name`, `iat`, `auth_time` (from the identity provider), `exp` at most 300 seconds after `iat`, and `nonce` when the request carried one.

#### Scenario: Audience

- **WHEN** an ID token issued to one deployment is presented to an app verifying against another deployment's client ID
- **THEN** its audience does not match

#### Scenario: Same subject as headers

- **WHEN** the same user signs in to a header-authenticated app and an SSO-enabled app
- **THEN** the ID token's `sub` equals the `X-Freepod-User` header the first app received

#### Scenario: Signing key rotation

- **WHEN** a new signing key has been added in front of the keyring
- **THEN** new ID tokens are signed with it, and the JWKS endpoint publishes both public keys

#### Scenario: Session ID

- **WHEN** a client redeems a code
- **THEN** the ID token carries the `sid` app authentication recorded for that sign-in

### Requirement: Back-channel logout tokens

When access for a subject is revoked, or an identity provider session ends after signing in to a client, on a client that declares `auth.oidc.backchannelLogoutPath`, the platform SHALL POST a logout token as `logout_token` in a form body to `https://<hostname><path>`, reaching the app through the platform's own ingress, without following redirects.

#### Scenario: App refuses the token

- **WHEN** the app answers a logout token for a revocation with any status other than `2xx`, or cannot be reached
- **THEN** the revocation fails and is not retried

#### Scenario: App refuses a sign-out

- **WHEN** the app answers a logout token for an ended session with any status other than `2xx`, or cannot be reached
- **THEN** the failure is logged, the sign-out is unaffected, and it is not retried

### Requirement: Logout token contents

A logout token SHALL be signed with the provider's current ID token key, with `typ: logout+jwt`. It SHALL carry the provider's issuer as `iss`, the client ID as `aud`, `iat`, `exp` at most 120 seconds later, a unique `jti`, `sub` and the back-channel logout event, and no `nonce`. A token for an ended session SHALL also carry that session's `sid` at the client; a token for a revocation SHALL carry no `sid`.

#### Scenario: Token contents

- **WHEN** the platform sends a logout token for Ana's subject to a client
- **THEN** the token verifies against the JWKS endpoint, its `aud` is the client ID, its `sub` is Ana's subject, and it has the `http://schemas.openid.net/event/backchannel-logout` event and no `nonce`

#### Scenario: Revocation ends every session

- **WHEN** the owner removes Ana from a deployment's access list
- **THEN** the logout token carries no `sid`

#### Scenario: Sign-out ends one session

- **WHEN** Ana signs out of the dashboard in a browser where she signed in to the deployment
- **THEN** the logout token carries the `sid` her ID token in that browser carried
