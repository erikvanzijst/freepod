## MODIFIED Requirements

### Requirement: Email verification is required
The system SHALL require email verification for new user accounts in the
`freepod` realm. Because the email claim is the sole join key between Keycloak
and Freepod's own user records, an unverified email is a privilege-escalation
vector and verification SHALL NOT be relaxed.

An account created through an identity provider configured to trust its email
assertions — currently only Google — SHALL be marked verified by that assertion
instead of by a Keycloak verification email. No other path SHALL mark an email
verified without the user following a Keycloak verification link.

#### Scenario: Email verification is required
- **WHEN** the `freepod` realm settings are inspected
- **THEN** `verifyEmail` is set to `true`

#### Scenario: Email is the identity join key
- **WHEN** Freepod resolves an authenticated caller to a user record
- **THEN** the lookup is performed on the verified email claim
- **AND** no Keycloak subject identifier is persisted by Freepod

#### Scenario: Trusted identity provider verifies the email
- **WHEN** an account is created by a first sign-in through Google
- **THEN** its email is marked verified without a Keycloak verification email

#### Scenario: Self-registration still verifies by email
- **WHEN** a user registers through the registration form
- **THEN** they must follow the Keycloak verification link before they can sign in
