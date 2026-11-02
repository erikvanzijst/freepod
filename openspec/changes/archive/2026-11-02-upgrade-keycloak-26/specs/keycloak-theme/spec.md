# Spec Delta

## Purpose

The Freepod branding of Keycloak's login, account and email pages: each theme
resolves on the running Keycloak, and no page a user can reach falls back to
stock Keycloak.

## ADDED Requirements

### Requirement: Every Freepod theme resolves on the running server

Each of the `freepod` login, account and email themes SHALL extend a parent
theme that the running Keycloak version ships. A theme whose parent is missing
is silently replaced by Keycloak's built-in theme, so a resolution failure is a
branding outage, not an error.

#### Scenario: No theme falls back

- **WHEN** Keycloak starts and serves the login page, the account console and a
  realm email
- **THEN** its log contains no "Failed to find" or "Not found parent theme"
  entry for any `freepod` theme

#### Scenario: The account console is branded

- **WHEN** a signed-in user opens `https://keycloak.freepod.eu/realms/freepod/account`
- **THEN** the console shows the Freepod logo and stylesheet, not stock Keycloak

### Requirement: Every reachable login page carries the Freepod styling

The login theme SHALL style every page a Freepod user can reach through the
`freepod` realm's flows, not only the sign-in form.

#### Scenario: Flow pages are styled

- **WHEN** a user opens any of: sign in, register, reset password, update
  password, verify email, update profile, Google account-link confirmation,
  device-code entry, or an error page
- **THEN** the page uses the Freepod surface, fonts, inputs and primary button

#### Scenario: Styling is checked on every upgrade

- **WHEN** the Keycloak version changes
- **THEN** each page above is reviewed in a browser before the new version
  serves production

### Requirement: The Google option follows Google's branding exactly once

The login page SHALL present the Google identity provider as a single "Sign in
with Google" button that meets Google's branding guidelines: the four-color G
mark and that label. The button and the "or" divider before it SHALL each
appear once.

#### Scenario: One mark, one label

- **WHEN** the sign-in page is rendered
- **THEN** the Google button shows exactly one G mark and exactly one "Sign in
  with Google" label

#### Scenario: One divider

- **WHEN** the sign-in page is rendered
- **THEN** exactly one "or" divider separates the password form from the Google
  button

### Requirement: Emails are branded

Keycloak's transactional emails (email verification, password reset, required
actions) SHALL use the Freepod email layout and call-to-action button.

#### Scenario: Verification email

- **WHEN** a newly registered user receives the email verification message
- **THEN** it uses the Freepod layout, with the verification link as a styled
  button
