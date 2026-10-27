# Spec Delta

## MODIFIED Requirements

### Requirement: The immich-sso chart is off unless enabled

The `immich-sso` chart SHALL offer Sign in with Freepod only when its values set `auth.enabled: true` with `auth.protocol: oidc`, and `auth.enabled` SHALL default to false. With it off, the chart SHALL configure Immich as the catalog Immich chart it was copied from does.

#### Scenario: Rendered without SSO

- **WHEN** the `immich-sso` chart is rendered with values that do not mention `auth`
- **THEN** Immich is configured without Freepod sign-in, with password login, as the catalog chart configures it

### Requirement: The sandbox product always uses SSO

The `immich-sso` product SHALL be visible only to administrators, SHALL set `auth.enabled: true`, `auth.protocol: oidc` and `auth.access: anyone` for every deployment as template system values, and SHALL offer tenants no value that changes them. It SHALL declare the web callback path `/auth/login`, the native redirect `app.immich:///oauth-callback` and the back-channel logout path `/api/oauth/backchannel-logout`, and nothing else.

#### Scenario: Tenant cannot turn SSO off

- **WHEN** a deployment of `immich-sso` is created with user values that try to set `auth.enabled: false`
- **THEN** the values are refused as invalid

#### Scenario: Hidden from end users

- **WHEN** an end user lists the products on offer
- **THEN** `immich-sso` is not among them
