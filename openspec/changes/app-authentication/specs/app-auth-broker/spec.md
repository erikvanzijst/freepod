## Purpose

The central half of app authentication: the one place that authenticates users against Freepod's identity provider on behalf of `custom` apps, records their consent, and hands each app's host a single-use proof of who signed in.

## ADDED Requirements

### Requirement: One login host per environment

The broker SHALL be served on `https://login.freepod.eu` in production and `https://login.dev.freepod.eu` in development. It SHALL be the only component of app authentication that communicates with the identity provider. Each environment's broker SHALL serve only that environment's deployments.

#### Scenario: Production app signs in through the production broker

- **WHEN** sign-in starts on a production app host
- **THEN** the browser is sent to `https://login.freepod.eu`

#### Scenario: Cross-environment request

- **WHEN** the production broker is asked to sign a user in to a hostname that belongs only to a development deployment
- **THEN** it refuses as it would for any unknown host

### Requirement: Only auth-enabled deployments are served

Before sending a browser to the identity provider, and again before issuing a code, the broker SHALL confirm that the requested host is the hostname of a `custom` deployment that is not deleted and has authentication enabled. The comparison SHALL be case-insensitive. Whether authentication is enabled SHALL be judged from the release the deployment is currently serving, not from settings not yet rolled out, so the broker agrees with what the edge enforces. This SHALL apply to wildcard-domain and custom-domain hostnames alike. For any other host, the broker SHALL show an error page and SHALL NOT redirect anywhere.

#### Scenario: Custom domain

- **WHEN** sign-in starts for `shop.example.com`, the hostname of an auth-enabled `custom` deployment
- **THEN** the broker proceeds

#### Scenario: Host without authentication enabled

- **WHEN** sign-in is requested for the hostname of a `custom` deployment that has not enabled authentication
- **THEN** the broker shows an error and issues no code

#### Scenario: Arbitrary host

- **WHEN** sign-in is requested for `evil.example`
- **THEN** the broker shows an error and does not redirect

#### Scenario: Authentication disabled mid-flow

- **WHEN** a deployment disables authentication after a user was sent to the identity provider, and the user then returns to the broker
- **THEN** the broker issues no code

### Requirement: Authentication against the identity provider

The broker SHALL authenticate users with the OpenID Connect authorization code flow. It SHALL use PKCE (`S256`), and SHALL validate `state` and `nonce`. It SHALL accept a user only when the ID token asserts `email_verified: true`. Tokens received from the identity provider SHALL NOT be persisted, and SHALL NOT be sent to any app or app host. A user who already has an active sign-in session at the identity provider SHALL NOT be asked for credentials again.

#### Scenario: Existing Freepod session

- **WHEN** a user signed in to Freepod starts sign-in on an app they have consented to before
- **THEN** they reach the app without entering credentials or seeing a page that needs interaction

#### Scenario: New user registers

- **WHEN** a user without a Freepod account chooses to register on the identity provider's page and verifies their email
- **THEN** sign-in continues to the app with the new account

#### Scenario: Unverified email

- **WHEN** the identity provider returns an ID token with `email_verified: false`
- **THEN** the broker issues no code and shows an error explaining the email must be verified

### Requirement: Any Freepod account may sign in

Any Freepod account with a verified email SHALL be able to sign in to any auth-enabled app. The broker SHALL NOT apply per-app allow or deny lists. Authorization inside the app is the app's responsibility.

#### Scenario: Stranger signs in

- **WHEN** a Freepod user with no relation to an app's owner signs in to that app
- **THEN** sign-in succeeds and the app receives their identity

### Requirement: Consent before first disclosure

The first time a user signs in to a given deployment, the broker SHALL show a consent page and SHALL issue no code until the user agrees. The page SHALL state:
- the app's hostname;
- that the app is operated by a Freepod user and not by Freepod;
- exactly what is disclosed: name, email address and a stable account identifier.

Agreement SHALL be recorded per user and deployment, together with the claims disclosed. It SHALL NOT be asked for again on that deployment unless the broker would disclose a claim the recorded consent does not cover. A deployment deleted and recreated under the same hostname is a different deployment, so consent is asked for again. Declining SHALL issue no code and SHALL NOT be recorded. The consent submission SHALL be protected against cross-site request forgery.

#### Scenario: First visit

- **WHEN** Alice signs in to `milk.erik.freepod.eu` for the first time
- **THEN** she sees a consent page naming `milk.erik.freepod.eu` and listing name, email and account identifier

#### Scenario: Returning visit

- **WHEN** Alice signs in to `milk.erik.freepod.eu` again a week later
- **THEN** she is not asked for consent

#### Scenario: Declined

- **WHEN** Alice declines consent
- **THEN** no code is issued, nothing is recorded, and she sees a page confirming the app received nothing

#### Scenario: More claims than consented

- **WHEN** a future version of the broker discloses a claim beyond those Alice consented to on `milk.erik.freepod.eu`
- **THEN** she is asked for consent again before any code is issued

#### Scenario: Recreated deployment

- **WHEN** the owner deletes the deployment and creates a new one with the same hostname
- **THEN** Alice is asked for consent again on her next sign-in

### Requirement: Single-use code handoff

After authentication and consent, the broker SHALL issue a code and redirect the browser to `https://<host>/.freepod/auth/callback`. The code SHALL be:
- random, with at least 128 bits of entropy;
- bound to the host, the user, the return target and the sign-in attempt that requested it;
- valid for at most 60 seconds;
- redeemable at most once.

The code SHALL NOT itself encode the user's identity in a way readable by whoever holds the URL.

#### Scenario: Code lifetime

- **WHEN** a code is presented 61 seconds after it was issued
- **THEN** it is rejected

### Requirement: Session renewal without interaction

When an app session expires, the next browser navigation to a protected path SHALL go through the broker again. If the user's sign-in at the identity provider is still active and consent exists, the user SHALL return to the app with a new session without any page needing interaction. If the user's Freepod account has been disabled or deleted, renewal SHALL fail.

#### Scenario: Next day

- **WHEN** Alice returns to the app after her 7-day session expired, while still signed in to Freepod
- **THEN** she lands on the requested page after redirects only

#### Scenario: Deleted account

- **WHEN** a user's Freepod account is deleted and their app session later expires
- **THEN** they cannot obtain a new session on any app
