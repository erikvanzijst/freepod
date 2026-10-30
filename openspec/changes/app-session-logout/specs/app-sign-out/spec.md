# Spec Delta

## Purpose

How ending a Keycloak SSO session ends the app sessions that browser started through Sign in with Freepod, so that signing out of the dashboard or of any app signs the browser out of every app it used.

## ADDED Requirements

### Requirement: Keycloak reports ended sessions to app-auth

The app authentication service SHALL accept OpenID Connect Back-Channel Logout tokens from its environment's identity provider at `POST /backchannel-logout`, as `logout_token` in a form body. It SHALL accept a token only when it is signed by the identity provider, its issuer is the `freepod` realm, its audience is the environment's app-authentication client, it carries the back-channel logout event and a `sid`, it has no `nonce`, and it was issued within the last two minutes.

#### Scenario: Valid token

- **WHEN** the identity provider posts a valid logout token for session `S`
- **THEN** app-auth answers `200` and treats `S` as ended

#### Scenario: Forged token

- **WHEN** anyone posts a logout token not signed by the identity provider
- **THEN** app-auth answers `400` and ends nothing

#### Scenario: Token without a session

- **WHEN** a correctly signed logout token carries a `sub` but no `sid`
- **THEN** app-auth answers `400` and ends nothing

#### Scenario: Other environment's client

- **WHEN** a logout token addressed to the other environment's app-authentication client is posted
- **THEN** app-auth answers `400` and ends nothing

### Requirement: The sign-out is acknowledged before it is passed on

App-auth SHALL record a session as ended before answering the identity provider, and SHALL answer without waiting for any app. When it cannot record the session as ended, it SHALL answer `500`. Receiving the same session's logout again SHALL have no further effect.

#### Scenario: Slow app

- **WHEN** a session ends whose browser signed in to an app that takes ten seconds to answer
- **THEN** app-auth answers the identity provider before contacting the app

#### Scenario: Repeated logout

- **WHEN** the identity provider posts the logout of an already ended session again
- **THEN** app-auth answers `200` and sends no further logout tokens

### Requirement: OIDC sign-ins are recorded against their Keycloak session

Whenever the provider issues an authorization code, app-auth SHALL record the Keycloak session the user signed in with, the deployment, the subject and the `sid` it gives that deployment. It SHALL keep at most one record per Keycloak session and deployment. When it cannot record the sign-in, it SHALL issue no code.

#### Scenario: Two apps in one browser

- **WHEN** a user signs in to Immich and Nextcloud in the same browser
- **THEN** two records exist for that browser's Keycloak session, one per deployment

#### Scenario: Signing in again

- **WHEN** a user signs in to the same app twice within one Keycloak session
- **THEN** one record exists for that session and deployment

#### Scenario: Database unavailable

- **WHEN** the sign-in cannot be recorded
- **THEN** the app receives `server_error` and no code

### Requirement: An ended session signs its browser out of OIDC apps

For each deployment recorded against an ended Keycloak session, app-auth SHALL send the deployment's back-channel logout path a logout token carrying the subject and that deployment's `sid`, when the deployment is still an OIDC client that declares one. It SHALL remove the session's sign-in records whatever the outcome of delivery.

#### Scenario: Signing out of the dashboard

- **WHEN** a user who signed in to Immich in this browser signs out of the dashboard
- **THEN** Immich receives a logout token with that browser's `sid`, and the user's Immich session in this browser ends

#### Scenario: Other devices are untouched

- **WHEN** the same user is also signed in to Immich on their phone and signs out of the dashboard on their laptop
- **THEN** the phone's Immich session continues

#### Scenario: App no longer uses OIDC

- **WHEN** a recorded deployment has since been deleted or stopped declaring a back-channel logout path
- **THEN** no logout token is sent to it

### Requirement: Delivery failures are logged, not retried

A logout token for an ended session SHALL be sent once, without following redirects, and given at most ten seconds. When the app answers with any status other than `2xx` or cannot be reached, app-auth SHALL log the deployment and the outcome and SHALL NOT retry.

#### Scenario: App is down

- **WHEN** a recorded app is scaled to zero when its user signs out
- **THEN** app-auth logs the failure, the sign-out still completes, and the app's session continues

### Requirement: Ended sessions end header-app sessions

The verifier SHALL treat a header-app session as invalid once the Keycloak session it came from has ended. A session that names no Keycloak session SHALL remain valid until it expires.

#### Scenario: Signing out of an app

- **WHEN** a user signed in to a header app and to Immich in one browser signs out of Immich
- **THEN** within ten seconds the header app treats that browser as signed out

#### Scenario: Another browser

- **WHEN** the same user is signed in to the header app in a second browser, with its own Keycloak session
- **THEN** that browser stays signed in

### Requirement: Sign-out records are kept only while they can matter

App-auth SHALL delete a sign-in record within a day of it becoming older than the realm's SSO session maximum lifespan of 30 days, and an ended-session record within a day of it becoming older than the header session lifetime of 7 days. A change to either lifetime SHALL change the matching retention.

#### Scenario: Browser that never signs out

- **WHEN** a sign-in record is 31 days old
- **THEN** it no longer exists

#### Scenario: Ended session past every cookie

- **WHEN** an ended-session record is 8 days old
- **THEN** it no longer exists
