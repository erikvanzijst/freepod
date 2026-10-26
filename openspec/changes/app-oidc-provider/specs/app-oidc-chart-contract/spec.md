# Spec Delta

## ADDED Requirements

### Requirement: SSO is declared in the deployment's values

A chart that offers Sign in with Freepod over OpenID Connect SHALL read it from `sso.enabled`, which defaults to false. A template MAY set `sso.enabled` as a system value, which then applies to every deployment of that template and overrides the user value. `sso.enabled` SHALL be independent of `auth.enabled`: enabling SSO SHALL NOT put the forward-auth verifier in front of the deployment.

#### Scenario: Default off

- **WHEN** a chart that supports SSO is rendered for a deployment whose values do not mention `sso`
- **THEN** the app is configured without Freepod sign-in, and the reconciler publishes no OIDC credentials for it

#### Scenario: SSO without forward-auth

- **WHEN** a deployment enables SSO and not `auth`
- **THEN** its routes carry no forward-auth middleware

### Requirement: The template declares its callbacks

A product that supports SSO SHALL declare, as template system values, the exact callback paths its app uses in `sso.redirectPaths`, and any native-client redirect URIs in `sso.nativeRedirectUris`. A template that declares no callback path SHALL NOT make its deployments clients, whatever their values say. A template MAY set `sso.pkce: false` only when its app cannot do PKCE.

#### Scenario: BookStack

- **WHEN** a BookStack template declares `sso.redirectPaths: ["/oidc/callback"]`
- **THEN** every deployment of that template may use exactly `https://<its hostname>/oidc/callback`

#### Scenario: Mobile app callback

- **WHEN** a template declares `sso.nativeRedirectUris: ["app.immich:///oauth-callback"]`
- **THEN** every deployment of that template may use that redirect URI, and no other custom-scheme URI

### Requirement: The reconciler publishes OIDC credentials

For a deployment whose merged values enable SSO, the reconciler SHALL publish a Kubernetes Secret in the deployment's namespace holding `OIDC_ISSUER`, `OIDC_CLIENT_ID` and `OIDC_CLIENT_SECRET`. It SHALL inject `caelus.oidc.issuer`, `caelus.oidc.clientId` and `caelus.oidc.secretName` into the chart values. The client secret SHALL NOT appear in chart values, in the release record or in logs.

#### Scenario: Credentials by reference

- **WHEN** the chart values the reconciler renders for an SSO-enabled deployment are inspected
- **THEN** they hold the issuer, the client ID and the Secret's name, and no client secret

### Requirement: Credentials go when SSO is turned off

When a deployment no longer enables SSO, the reconciler SHALL remove its OIDC Secret and SHALL inject no `caelus.oidc` block.

#### Scenario: Turning SSO off

- **WHEN** a deployment that had SSO enabled is redeployed with `sso.enabled: false`
- **THEN** its OIDC Secret no longer exists and its values carry no `caelus.oidc` block

### Requirement: Charts re-apply OIDC settings on every start

A chart SHALL apply the issuer, client ID and client secret from the published Secret to its app on every start, including apps that keep their OIDC settings in their own database, so a rotated secret takes effect on the next restart.

#### Scenario: Rotated client key

- **WHEN** the environment's client keyring gains a new key and the reconciler republishes a deployment's Secret
- **THEN** after the app restarts, it authenticates with the new secret

### Requirement: Apps that decide access close their own doors

A chart that relies on its app to decide who may sign in SHALL turn off the app's automatic registration of new SSO users and its local sign-up, so that a Freepod account the app's admin did not invite is refused and nobody can pre-create an account under another person's email.

#### Scenario: Uninvited account

- **WHEN** a Freepod account the app's admin never invited signs in through SSO
- **THEN** the app refuses it and creates no account

#### Scenario: Pre-created account

- **WHEN** someone tries to register locally in the app with an email they do not control
- **THEN** the app offers no local sign-up
