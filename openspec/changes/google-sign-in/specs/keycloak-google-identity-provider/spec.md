## Purpose

Lets people sign up for and sign in to Freepod with their Google account, as an alternative
to a Freepod password, without creating a second account for anyone who already has one.

## ADDED Requirements

### Requirement: Google is an identity provider on the Freepod realm

The `freepod` realm SHALL offer Google as an OpenID Connect identity provider, declared in
Terraform alongside the rest of the realm configuration. Its OAuth client secret SHALL be
supplied from a sensitive Terraform variable held in the manually maintained
`secrets.auto.tfvars`, never committed.

#### Scenario: The provider is configured on the realm

- **WHEN** the identity providers of realm `freepod` are listed
- **THEN** a provider of type `google` is present and enabled

#### Scenario: The login page offers Google

- **WHEN** a visitor opens the `freepod` realm login page
- **THEN** a "Sign in with Google" option is shown alongside the email and password form

#### Scenario: The secret is not in the repository

- **WHEN** the Terraform configuration is inspected
- **THEN** the Google client secret appears only as a variable reference, and its value is
  read from `secrets.auto.tfvars`

### Requirement: A first Google sign-in creates a verified account

A Google sign-in whose email belongs to no existing account SHALL create a `freepod`-realm
account without further prompts. The account's email SHALL be the address Google asserts
and SHALL be marked verified without a Keycloak verification email. Its username SHALL be
that email address, as for any self-registered account.

#### Scenario: New user signs up with Google

- **WHEN** a person with no Freepod account signs in with Google as `ada@gmail.com`
- **THEN** a `freepod`-realm account is created with email `ada@gmail.com` and username
  `ada@gmail.com`
- **AND** its email is marked verified
- **AND** no verification email is sent and no profile form is shown

#### Scenario: The new account reaches Freepod

- **WHEN** that person completes the sign-in to `freepod.eu`
- **THEN** Freepod resolves them to a user record for `ada@gmail.com`, exactly as for an
  account created through the registration form

### Requirement: A Google identity joins an existing account and never duplicates it

When a Google sign-in presents an email that already belongs to a `freepod`-realm account,
the system SHALL NOT create a second account and SHALL NOT modify the existing one. It SHALL
ask the user to confirm linking and to prove control of the existing account — by an
emailed link or by that account's password — before attaching the Google identity to it.
Once linked, both sign-in methods SHALL reach the same account.

The system SHALL NOT link a Google identity to an existing account automatically on email
match alone. An existing account may carry a password chosen by someone who registered the
address without controlling it; linking without proof would hand that person the account.

#### Scenario: Existing password user signs in with Google

- **WHEN** a user with a password account for `bob@example.com` signs in with Google as
  `bob@example.com` for the first time
- **THEN** no new account is created
- **AND** they are asked to confirm linking the Google identity to the existing account
- **AND** they must follow an emailed link or enter the existing account's password
  before the link is made

#### Scenario: Linked account resolves to the same Freepod user

- **WHEN** that user has completed linking and signs in with Google, and separately with
  their password
- **THEN** both sign-ins resolve to the same Freepod user record, with the same deployments

#### Scenario: Linking does not alter the existing account

- **WHEN** a Google identity is linked to an existing account
- **THEN** the account's email, username, name and credentials are unchanged

#### Scenario: Unproven link is refused

- **WHEN** a user abandons the confirmation or verification step
- **THEN** no Google identity is linked and no account is created

#### Scenario: Password registration after Google sign-up

- **WHEN** a user who signed up with Google as `ada@gmail.com` later submits the
  registration form with `ada@gmail.com`
- **THEN** registration is refused because the email is already in use
- **AND** the user can add a password to the existing account through self-service
  password reset

### Requirement: Google attributes are imported once

The identity provider SHALL import profile attributes from Google only when it creates an
account, and SHALL NOT overwrite them on later sign-ins. Freepod resolves callers by the
Keycloak email, so a Google-side address change propagated on sign-in would move the caller
to a different, empty Freepod account.

Switching to a mode that syncs attributes on every sign-in SHALL wait until Freepod resolves
callers by a key that survives an email change.

#### Scenario: Sync mode is import

- **WHEN** the Google identity provider settings are inspected
- **THEN** its sync mode is `IMPORT`

#### Scenario: A Google-side email change does not move the account

- **WHEN** a linked user changes the email on their Google account and signs in with Google
  again
- **THEN** their Keycloak email is unchanged
- **AND** they resolve to the same Freepod user record as before

### Requirement: Google sign-in is realm-wide and grants no access by itself

The Google option SHALL be available to every client of the `freepod` realm without
per-client configuration, and SHALL grant nothing beyond an ordinary account. Access that
is gated by group membership SHALL remain gated for accounts created or linked through
Google.

#### Scenario: Available to every realm client

- **WHEN** a user authenticates through the production or development oauth2-proxy
  client, a CLI client, the app-auth broker or Grafana
- **THEN** the login page offers Google

#### Scenario: Development access still requires the group

- **WHEN** a Google-created account that is not a member of `freepod-dev` signs in to
  `dev.freepod.eu`
- **THEN** access is denied, as for any account outside that group

#### Scenario: No groups are assigned on creation

- **WHEN** an account is created through Google
- **THEN** it belongs to no group
