# Spec Delta

## ADDED Requirements

### Requirement: The dashboard session follows the SSO session

oauth2-proxy SHALL NOT request `offline_access`, so its refresh token belongs to the browser's Keycloak SSO session, the one app sign-ins reuse. It SHALL refresh a session older than one minute. Once the SSO session has ended, the dashboard SHALL treat the browser as signed out within a minute.

#### Scenario: Signing out of an app

- **WHEN** a user signs out of an app that ended their Keycloak SSO session, and reloads the dashboard a minute later
- **THEN** the dashboard shows them signed out

#### Scenario: Silent app sign-in

- **WHEN** a user signed in to the dashboard opens an app they have consented to
- **THEN** they are not asked for a password

#### Scenario: Idle but signed in

- **WHEN** a user returns to the dashboard after six days without using it, with no sign-out anywhere
- **THEN** they are still signed in
