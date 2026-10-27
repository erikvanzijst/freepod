# immich-sso Specification

## Purpose

Defines how an SSO-enabled Immich deployment signs people in with their Freepod account on the web and in the mobile app, who may sign in, how the owner's admin account comes to exist, and what signing out does.

## Requirements

### Requirement: The catalog Immich product is untouched

This capability SHALL be delivered only through its own chart, `immich-sso`, and its own product. The catalog Immich chart, its product, its templates and its deployments SHALL NOT change because of it.

#### Scenario: Catalog Immich deployment

- **WHEN** a deployment of the catalog Immich product is reconciled after this capability ships
- **THEN** it renders from the same chart version with the same resources as before

### Requirement: The immich-sso chart is off unless enabled

The `immich-sso` chart SHALL offer Sign in with Freepod only when its values enable `sso.enabled`, which SHALL default to false. With it off, the chart SHALL configure Immich as the catalog Immich chart it was copied from does.

#### Scenario: Rendered without SSO

- **WHEN** the `immich-sso` chart is rendered with values that do not mention `sso`
- **THEN** Immich is configured without Freepod sign-in, with password login, as the catalog chart configures it

### Requirement: The sandbox product always uses SSO

The `immich-sso` product SHALL be visible only to administrators, SHALL enable SSO for every deployment as a template system value, and SHALL offer tenants no value that turns it off. It SHALL declare the web callback path `/auth/login` and the native redirect `app.immich:///oauth-callback`, and nothing else.

#### Scenario: Tenant cannot turn SSO off

- **WHEN** a deployment of `immich-sso` is created with user values that try to set `sso.enabled: false`
- **THEN** the values are refused as invalid

#### Scenario: Hidden from end users

- **WHEN** an end user lists the products on offer
- **THEN** `immich-sso` is not among them

### Requirement: Sign in with Freepod on the web

With SSO enabled, the web sign-in page SHALL send the visitor straight to Sign in with Freepod, and SHALL offer no password form. A successful sign-in SHALL land the user in Immich, signed in as the Immich user linked to their Freepod account.

#### Scenario: Web sign-in

- **WHEN** a person whose Freepod account is linked to an Immich user opens the instance's sign-in page
- **THEN** they are sent to Freepod, sign in, and arrive in Immich as that user

#### Scenario: No password login

- **WHEN** someone submits an email and password to the instance's password login
- **THEN** Immich refuses it

### Requirement: Sign in with Freepod in the mobile app

With SSO enabled, the Immich mobile app SHALL be able to sign in with Freepod, including a person's first sign-in to the instance, which shows the consent page.

#### Scenario: First sign-in from the phone

- **WHEN** a person who never consented to the instance signs in from the mobile app and allows sharing on the consent page
- **THEN** the browser returns to the app and the app is signed in

### Requirement: Only accounts the admin created may sign in

With SSO enabled, Immich SHALL NOT create an account for a Freepod user it does not know. It SHALL link a Freepod account to the Immich user with the same email on that account's first sign-in, and from then on SHALL admit only the Freepod account it linked to that user.

#### Scenario: Uninvited Freepod account

- **WHEN** a verified Freepod account with no matching Immich user signs in
- **THEN** Immich refuses it and creates no account

#### Scenario: Invited by the admin

- **WHEN** the admin creates an Immich user with a person's Freepod email, and that person signs in with Freepod
- **THEN** they are signed in as that user

#### Scenario: Another account with a linked email

- **WHEN** an Immich user is linked to one Freepod subject, and a sign-in arrives with the same email but a different subject
- **THEN** Immich refuses it

### Requirement: Access settings cannot be changed in the app

With SSO enabled, the instance's sign-in settings SHALL be fixed by the deployment. An Immich admin SHALL NOT be able to turn on auto-registration or password login, or change the identity provider, from Immich's own screens.

#### Scenario: Admin tries to turn on auto-registration

- **WHEN** an Immich admin opens the authentication settings
- **THEN** the settings are read-only

### Requirement: Admin rights stay inside Immich

Signing in with Freepod SHALL NOT grant or remove Immich admin rights, and SHALL NOT set a user's storage quota. Those SHALL change only through Immich's own administration.

#### Scenario: Ordinary user signs in

- **WHEN** a non-admin Immich user signs in with Freepod
- **THEN** they remain a non-admin user with an unchanged quota

### Requirement: The owner is the first admin

With SSO enabled, a new instance SHALL have an admin account under the owner's Freepod email before it serves any outside request, so that the owner's first sign-in with Freepod lands as admin and nobody else can claim the admin account. The deployment SHALL fail to render when SSO is enabled and the owner's email is unknown.

#### Scenario: Owner's first sign-in

- **WHEN** the owner signs in with Freepod to a newly created instance
- **THEN** they are the instance's admin

#### Scenario: Nobody can claim a fresh instance

- **WHEN** anyone other than the platform requests the instance before its admin account exists
- **THEN** the request is not served

#### Scenario: Restart

- **WHEN** an instance that already has an admin restarts
- **THEN** it keeps its existing admin, and no second admin is created

### Requirement: The client secret stays out of chart values

The deployment SHALL take its client secret from the published OIDC Secret each time the server starts, and SHALL NOT carry it in chart values or in any ConfigMap.

#### Scenario: Inspecting the release

- **WHEN** the release's rendered values and ConfigMaps are inspected
- **THEN** none of them contains the client secret

#### Scenario: Rotated secret

- **WHEN** the OIDC Secret is republished with a new client secret and the server restarts
- **THEN** sign-in works with the new secret

### Requirement: Signing out returns to the instance

Signing out of Immich on the web SHALL end the user's Freepod session and then return the browser to the instance's root.

#### Scenario: Web sign-out

- **WHEN** a signed-in user signs out of Immich in the browser and confirms on Freepod's sign-out prompt
- **THEN** their Freepod session ends and they land on the instance's root, which asks them to sign in again
