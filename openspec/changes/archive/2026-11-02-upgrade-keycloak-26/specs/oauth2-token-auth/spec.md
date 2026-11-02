# Spec Delta

## MODIFIED Requirements

### Requirement: Access tokens carry the claims the edge authorizes on

The system SHALL assign the CLI clients the client scopes that carry the
identity and membership claims the edge depends on, so that a bearer-
authenticated request is authorized on the same evidence as a browser session.

#### Scenario: Email claim is present

- **WHEN** an access token obtained through either CLI client is decoded
- **THEN** it carries an `email` claim

#### Scenario: Groups claim is present

- **WHEN** an access token obtained through either CLI client is decoded
- **THEN** it carries a `groups` claim with bare group names
- **AND** the claim is present in the access token, not only in the ID token or
  userinfo response

#### Scenario: Subject claim is present

- **WHEN** an access token obtained through either CLI client is decoded
- **THEN** it carries a `sub` claim
- **AND** a bearer-authenticated request reaches the API with that subject as
  the caller's identity, exactly as a browser session for the same user does
