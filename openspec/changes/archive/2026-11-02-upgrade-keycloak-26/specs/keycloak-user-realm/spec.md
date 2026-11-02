# Spec Delta

## ADDED Requirements

### Requirement: Every client issues the subject in its access tokens

Every client in the `freepod` realm SHALL have Keycloak's `basic` client scope as a default scope, because it carries the mapper that puts `sub` (and `auth_time`) into access tokens. Without it, access tokens carry no subject, while ID tokens and userinfo still do. That makes a token presented as a bearer credential the one place the subject goes missing.

#### Scenario: The basic scope is assigned to every client

- **WHEN** the default client scopes of `freepod-prod`, `freepod-dev`, `freepod-cli-prod`, `freepod-cli-dev`, `freepod-apps-prod`, `freepod-apps-dev` and `grafana` are inspected
- **THEN** each includes `basic`

#### Scenario: An access token carries the subject

- **WHEN** an access token issued to any of those clients is decoded
- **THEN** it carries a `sub` claim equal to the user's Keycloak ID

#### Scenario: Apply does not strip it

- **WHEN** `terraform apply` runs in `tf/deps`
- **THEN** no client loses the `basic` scope

### Requirement: Users are not shown a username

The `freepod` realm's user profile SHALL let only administrators view and edit the `username` attribute. The username is always the email address, so showing it to the user repeats the email field. The realm's user profile SHALL be managed by Terraform, so that this, and every other attribute's settings, are explicit and not Keycloak's version-dependent default.

#### Scenario: Personal info shows no username

- **WHEN** a signed-in user opens Personal info in the account console
- **THEN** it shows email, first name and last name, and no username field

#### Scenario: Administrators still see the username

- **WHEN** an administrator opens a user in the admin console
- **THEN** the username is shown

#### Scenario: Tokens still carry the username

- **WHEN** an access token issued to any `freepod` realm client is decoded
- **THEN** its `preferred_username` claim is the user's email address

#### Scenario: Apply leaves the profile unchanged

- **WHEN** `terraform plan` runs in `tf/deps` after the profile has been applied
- **THEN** it shows no change to the realm's user profile

### Requirement: Self-registration verifies the email before a password is set

Self-registration SHALL follow Keycloak's default flow for a realm that requires email verification. The registration form collects the email address and name only. The user proves control of the address through the emailed link, and only then sets a password.

#### Scenario: The registration form asks for no password

- **WHEN** a prospective user opens the registration form
- **THEN** it asks for email, first name and last name, and presents no password field

#### Scenario: A password is set after verification

- **WHEN** a newly registered user follows the verification link in their email
- **THEN** they are asked to set a password
- **AND** they are signed in once it is set

#### Scenario: An unverified registration holds no credential

- **WHEN** a user has registered but not yet followed the verification link
- **THEN** the account has no password, and no one can sign in to it with one
