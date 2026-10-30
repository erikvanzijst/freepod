# Spec Delta

## MODIFIED Requirements

### Requirement: Authentication against the identity provider

The broker SHALL authenticate users with the OpenID Connect authorization code flow. It SHALL use PKCE (`S256`), and SHALL validate `state` and `nonce`. It SHALL accept a user only when the ID token asserts `email_verified: true` and names the identity provider's session in `sid`; the broker SHALL keep that session ID for the sign-in. Tokens received from the identity provider SHALL NOT be persisted, and SHALL NOT be sent to any app or app host. A user who already has an active sign-in session at the identity provider SHALL NOT be asked for credentials again.

#### Scenario: Existing Freepod session

- **WHEN** a user signed in to Freepod starts sign-in on an app they have consented to before
- **THEN** they reach the app without entering credentials or seeing a page that needs interaction

#### Scenario: New user registers

- **WHEN** a user without a Freepod account chooses to register on the identity provider's page and verifies their email
- **THEN** sign-in continues to the app with the new account

#### Scenario: Unverified email

- **WHEN** the identity provider returns an ID token with `email_verified: false`
- **THEN** the broker issues no code and shows an error explaining the email must be verified

#### Scenario: No session ID

- **WHEN** the identity provider returns an ID token without `sid`
- **THEN** the broker issues no code and shows an error asking the user to try again later

### Requirement: Single-use code handoff

After authentication and consent, the broker SHALL issue a code and redirect the browser to `https://<host>/.freepod/auth/callback`. The code SHALL be:
- random, with at least 128 bits of entropy;
- bound to the host, the user, the identity provider session, the return target and the sign-in attempt that requested it;
- valid for at most 60 seconds;
- redeemable at most once.

The code SHALL NOT itself encode the user's identity in a way readable by whoever holds the URL. The session the app host issues for a redeemed code SHALL name the identity provider session the code was bound to.

#### Scenario: Code lifetime

- **WHEN** a code is presented 61 seconds after it was issued
- **THEN** it is rejected

#### Scenario: Session names its origin

- **WHEN** a user signs in to a header app from a browser whose identity provider session is `S`
- **THEN** the app session names `S`, so ending `S` ends it
