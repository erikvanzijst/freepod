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

### Requirement: Native redirect URIs come only from the template

A chart whose app has native clients that need a custom-scheme redirect SHALL declare those URIs in the template's system value `sso.redirectUris`. User values SHALL NOT be able to add redirect URIs.

#### Scenario: Mobile app callback

- **WHEN** a template declares `sso.redirectUris: ["app.immich:///oauth-callback"]`
- **THEN** every deployment of that template may use that redirect URI, and no other custom-scheme URI
