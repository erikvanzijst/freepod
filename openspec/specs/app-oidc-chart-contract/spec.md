# app-oidc-chart-contract Specification

## Purpose

Defines how a deployment opts in to Sign in with Freepod over OpenID Connect, what its template must declare, what the reconciler publishes and injects for it, and what a chart that offers it owes the app it configures.

## Requirements

### Requirement: SSO is declared in the deployment's values

A chart that offers Sign in with Freepod over OpenID Connect SHALL read it from `auth.enabled` together with `auth.protocol: oidc`. With `auth.protocol: oidc`, enabling authentication SHALL NOT put the forward-auth verifier in front of the deployment.

#### Scenario: Default off

- **WHEN** a chart that supports SSO is rendered for a deployment whose values do not mention `auth`
- **THEN** the app is configured without Freepod sign-in, and the reconciler publishes no OIDC credentials for it

#### Scenario: SSO without forward-auth

- **WHEN** a deployment's values set `auth.enabled: true` and `auth.protocol: oidc`
- **THEN** its routes carry no forward-auth middleware

### Requirement: A template's switch is a default

A template MAY set `auth.enabled` and `auth.protocol: oidc` as system values. They SHALL be the default for every deployment of that template, and a user value SHALL override them as it overrides any chart value. A template that must not be overridden SHALL leave `auth` out of its user values schema.

#### Scenario: Forced on by the template

- **WHEN** a template sets `auth.enabled: true` and `auth.protocol: oidc` as system values and its user values schema has no `auth` property
- **THEN** every deployment of the template enables SSO, and no tenant can turn it off

### Requirement: The template declares its callbacks

A product that supports SSO SHALL declare, as template system values, the exact callback paths its app uses in `auth.oidc.redirectPaths`, and any native-client redirect URIs in `auth.oidc.nativeRedirectUris`. A template that declares no callback path SHALL NOT make its deployments clients, whatever their values say. A template MAY set `auth.oidc.pkce: false` only when its app cannot do PKCE.

#### Scenario: BookStack

- **WHEN** a BookStack template declares `auth.oidc.redirectPaths: ["/oidc/callback"]`
- **THEN** every deployment of that template may use exactly `https://<its hostname>/oidc/callback`

#### Scenario: Mobile app callback

- **WHEN** a template declares `auth.oidc.nativeRedirectUris: ["app.immich:///oauth-callback"]`
- **THEN** every deployment of that template may use that redirect URI, and no other custom-scheme URI

### Requirement: The reconciler publishes OIDC credentials

For a deployment whose merged values set `auth.enabled: true` and `auth.protocol: oidc`, the reconciler SHALL publish a Kubernetes Secret in the deployment's namespace holding `OIDC_ISSUER`, `OIDC_CLIENT_ID` and `OIDC_CLIENT_SECRET`. It SHALL inject `caelus.oidc.issuer`, `caelus.oidc.clientId` and `caelus.oidc.secretName` into the chart values. The client secret SHALL NOT appear in chart values, in the release record or in logs.

#### Scenario: Credentials by reference

- **WHEN** the chart values the reconciler renders for an SSO-enabled deployment are inspected
- **THEN** they hold the issuer, the client ID and the Secret's name, and no client secret

#### Scenario: Header authentication

- **WHEN** a deployment's merged values set `auth.enabled: true` with `auth.protocol` left at `header`
- **THEN** the reconciler publishes no OIDC Secret and injects no `caelus.oidc` block

### Requirement: Credentials go when SSO is turned off

When a deployment no longer sets both `auth.enabled: true` and `auth.protocol: oidc`, the reconciler SHALL remove its OIDC Secret and SHALL inject no `caelus.oidc` block.

#### Scenario: Turning SSO off

- **WHEN** a deployment that had SSO enabled is redeployed with `auth.enabled: false`
- **THEN** its OIDC Secret no longer exists and its values carry no `caelus.oidc` block

### Requirement: Charts re-apply OIDC settings on every start

A chart SHALL apply the issuer, client ID and client secret from the published Secret to its app on every start, including apps that keep their OIDC settings in their own database, so a rotated secret takes effect on the next restart.

#### Scenario: Rotated client key

- **WHEN** the environment's client keyring gains a new key and the reconciler republishes a deployment's Secret
- **THEN** after the app restarts, it authenticates with the new secret

### Requirement: Apps that decide access close their own doors

A chart with `auth.access: anyone` that relies on its app to decide who may sign in SHALL turn off the app's automatic registration of new SSO users and its local sign-up, so that a Freepod account the app's admin did not invite is refused and nobody can pre-create an account under another person's email.

#### Scenario: Uninvited account

- **WHEN** a Freepod account the app's admin never invited signs in through SSO
- **THEN** the app refuses it and creates no account

#### Scenario: Pre-created account

- **WHEN** someone tries to register locally in the app with an email they do not control
- **THEN** the app offers no local sign-up

### Requirement: The template may declare a back-channel logout path

A template whose app accepts OpenID Connect Back-Channel Logout MAY declare, as the system value `auth.oidc.backchannelLogoutPath`, the path on the deployment's hostname where the app receives logout tokens. The path SHALL follow the rules for callback paths. A template that declares none SHALL get no logout tokens.

#### Scenario: Immich

- **WHEN** a template declares `auth.oidc.backchannelLogoutPath: "/api/oauth/backchannel-logout"`
- **THEN** the platform delivers logout tokens for its deployments to `https://<hostname>/api/oauth/backchannel-logout`
