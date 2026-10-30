# Spec Delta

## MODIFIED Requirements

### Requirement: The immich-sso chart is off unless enabled

The `immich-sso` chart SHALL offer Sign in with Freepod only when its values set `auth.enabled: true` with `auth.protocol: oidc`, and `auth.enabled` SHALL default to false. With it off, the chart SHALL configure Immich as the catalog Immich chart it was copied from does.

#### Scenario: Rendered without SSO

- **WHEN** the `immich-sso` chart is rendered with values that do not mention `auth`
- **THEN** Immich is configured without Freepod sign-in, with password login, as the catalog chart configures it

#### Scenario: SSO without an access list

- **WHEN** the chart is rendered with `auth.enabled: true` and `auth.protocol: oidc`, and `auth.access` is not `listed`
- **THEN** the render fails

### Requirement: The sandbox product always uses SSO

The `immich-sso` product SHALL be visible only to administrators, SHALL set `auth.enabled: true`, `auth.protocol: oidc` and `auth.access: listed` for every deployment as template system values, and SHALL offer tenants no value that changes them. It SHALL declare the web callback path `/auth/login`, the native redirect `app.immich:///oauth-callback` and the back-channel logout path `/api/oauth/backchannel-logout`, and nothing else.

#### Scenario: Tenant cannot turn SSO off

- **WHEN** a deployment of `immich-sso` is created with user values that try to set `auth.enabled: false`
- **THEN** the values are refused as invalid

#### Scenario: Hidden from end users

- **WHEN** an end user lists the products on offer
- **THEN** `immich-sso` is not among them

## ADDED Requirements

### Requirement: The people the owner admits are registered on first sign-in

With SSO enabled, Freepod's access list SHALL decide who may sign in, and Immich SHALL create an account for an admitted person the first time they sign in, named from their Freepod profile and with no password. A person who already has an Immich user with the same email SHALL be signed in as that user. From then on Immich SHALL admit only the Freepod account it linked to that user.

#### Scenario: Listed person signs in for the first time

- **WHEN** a person on the deployment's access list signs in with Freepod and Immich has no user with their email
- **THEN** Immich creates a non-admin user with their Freepod name and email, and signs them in

#### Scenario: Person not on the list

- **WHEN** a Freepod account that is neither the owner nor on the access list signs in
- **THEN** the provider refuses it and Immich creates no account

#### Scenario: Another account with a linked email

- **WHEN** an Immich user is linked to one Freepod subject, and a sign-in arrives with the same email but a different subject
- **THEN** Immich refuses it

### Requirement: Sign-in settings are fixed by the deployment

With SSO enabled, the instance's sign-in settings SHALL be fixed by the deployment. An Immich admin SHALL NOT be able to turn off auto-registration, turn on password login, or change the identity provider, from Immich's own screens.

#### Scenario: Admin opens the authentication settings

- **WHEN** an Immich admin opens the authentication settings
- **THEN** the settings are read-only

## REMOVED Requirements

### Requirement: Only accounts the admin created may sign in

**Reason**: Immich's intended OIDC model is that the identity provider decides who gets in and Immich registers them; the access list now does the deciding. Admitting only admin-created users relied on email auto-linking, which Immich is removing (immich-app/immich#27871).
**Migration**: The owner adds people in the deployment's Access dialog instead of creating them in Immich. Users created in Immich before the change keep signing in, linked by subject.

### Requirement: Access settings cannot be changed in the app

**Reason**: Replaced by "Sign-in settings are fixed by the deployment": auto-registration is now on, and the admin must not be able to turn it off.
**Migration**: None; the deployment's config file still locks the settings.
