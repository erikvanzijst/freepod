# app-auth-broker Specification

## Purpose

The central half of app authentication: the one place that authenticates users against Freepod's identity provider on behalf of tenant apps, records their consent, and hands each app's host a single-use proof of who signed in.

## Requirements

### Requirement: One login host per environment

The broker SHALL be served on `https://login.freepod.eu` in production and `https://login.dev.freepod.eu` in development. It SHALL be the only component of app authentication that communicates with the identity provider. Each environment's broker SHALL serve only that environment's deployments.

#### Scenario: Production app signs in through the production broker

- **WHEN** sign-in starts on a production app host
- **THEN** the browser is sent to `https://login.freepod.eu`

#### Scenario: Cross-environment request

- **WHEN** the production broker is asked to sign a user in to a hostname that belongs only to a development deployment
- **THEN** it refuses as it would for any unknown host

### Requirement: Only deployments with authentication enabled are served

Before sending a browser to the identity provider, and again before issuing a code, the broker SHALL confirm that the requested host is the hostname of a deployment that is not deleted and has header authentication enabled, whatever its product. The comparison SHALL be case-insensitive. Whether header authentication is enabled SHALL be judged from the release the deployment is currently serving, not from settings not yet rolled out, so the broker agrees with what the edge enforces: `auth.enabled` and `auth.protocol` each from the release's user value when it sets one, otherwise the template's system value, otherwise the contract's default, and enabled only when `auth.enabled` is true and `auth.protocol` is `header`. This SHALL apply to wildcard-domain and custom-domain hostnames alike. For any other host, the broker SHALL show an error page and SHALL NOT redirect anywhere.

#### Scenario: Custom domain

- **WHEN** sign-in starts for `shop.example.com`, the hostname of an auth-enabled `custom` deployment
- **THEN** the broker proceeds

#### Scenario: Host without authentication enabled

- **WHEN** sign-in is requested for the hostname of a deployment that has not enabled authentication
- **THEN** the broker shows an error and issues no code

#### Scenario: Arbitrary host

- **WHEN** sign-in is requested for `evil.example`
- **THEN** the broker shows an error and does not redirect

#### Scenario: Authentication disabled mid-flow

- **WHEN** a deployment disables authentication after a user was sent to the identity provider, and the user then returns to the broker
- **THEN** the broker issues no code

#### Scenario: Another product

- **WHEN** sign-in starts for the hostname of an auth-enabled deployment of a product other than `custom`
- **THEN** the broker proceeds

#### Scenario: Enabled by the template

- **WHEN** sign-in starts for a deployment whose template sets `auth.enabled: true` as a system value and whose user values say nothing about `auth`
- **THEN** the broker proceeds

#### Scenario: User value over the template's default

- **WHEN** a deployment's template sets `auth.enabled: true` as a system value and its user values set `auth.enabled: false`
- **THEN** the broker treats authentication as disabled, as the chart renders it

#### Scenario: OIDC deployment

- **WHEN** header sign-in is requested for the hostname of a deployment with `auth.enabled: true` and `auth.protocol: oidc`
- **THEN** the broker shows an error and issues no code

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

Any Freepod account with a verified email SHALL be able to sign in to any auth-enabled app whose serving release has `auth.access: anyone`, and authorization inside such an app is the app's responsibility. For an app with `auth.access: listed`, the broker SHALL admit only the deployment's owner and the people on its access list, and SHALL refuse anyone else after they authenticate and before any consent page, with the no-access page on the broker's host and no code.

#### Scenario: Stranger signs in

- **WHEN** a Freepod user with no relation to an app's owner signs in to an app with `auth.access: anyone`
- **THEN** sign-in succeeds and the app receives their identity

#### Scenario: Stranger on a listed app

- **WHEN** a Freepod user who is neither the owner nor listed signs in to an app with `auth.access: listed`
- **THEN** the broker shows the no-access page, shows no consent page, and issues no code

#### Scenario: Owner on a listed app

- **WHEN** the owner signs in to their app with `auth.access: listed` and an empty list
- **THEN** sign-in succeeds

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

### Requirement: Signing out at the identity provider

The broker SHALL offer a sign-out entry point that takes the app host and the return target. Before redirecting anywhere, it SHALL confirm the host exactly as sign-in does (see *Only auth-enabled deployments are served*); for any other host it SHALL show an error page and SHALL NOT redirect.

For an eligible host, the broker SHALL end the user's sign-in at the identity provider through the provider's own logout, naming the broker's client and a single fixed post-logout landing on the broker's host. The app host and return target SHALL travel in a value only the broker can read or produce, that expires within 10 minutes. The broker SHALL NOT keep identity-provider tokens in order to sign out; the identity provider MAY ask the user to confirm signing out.

On the post-logout landing, the broker SHALL redirect to `https://<host><return target>` only when that value is intact and unexpired. The return target SHALL pass the same same-host check the verifier applies. Otherwise, the broker SHALL show a page stating the user is signed out, and SHALL NOT redirect.

Sign-out SHALL work whether or not the user still has a sign-in session at the identity provider.

#### Scenario: Sign-out from an app

- **WHEN** a browser arrives at the broker's sign-out for `milk.erik.freepod.eu` with return target `/lists`
- **THEN** it is sent to the identity provider's logout, and after it completes lands on `https://milk.erik.freepod.eu/lists`

#### Scenario: Sign-out for an arbitrary host

- **WHEN** sign-out is requested for `evil.example`
- **THEN** the broker shows an error, does not redirect, and does not contact the identity provider

#### Scenario: Forged or expired return

- **WHEN** the post-logout landing is opened with a return value the broker did not produce, or one older than 10 minutes
- **THEN** the broker shows a signed-out page and does not redirect

#### Scenario: No identity-provider session

- **WHEN** a user whose identity-provider sign-in already ended signs out of an app
- **THEN** they still land on the app's return target

### Requirement: Preview hostnames sign in as their deployment

When the requested host is not itself a deployment's hostname, sits directly under the tenant domain, and its first label begins with `preview-`, as in `preview-<label>.<tenant domain>`, the broker SHALL treat it as the deployment at `<label>.<tenant domain>` (the host with that prefix removed), provided that deployment qualifies under *Only auth-enabled deployments are served*. Hostname validation reserves the prefix under the tenant domain only, so the broker MUST NOT apply this to any other domain: a custom domain `preview-<rest>` may belong to an unrelated account. The broker SHALL derive this from the hostname and its own records only, never from anything in the request naming an alias.

#### Scenario: Preview of an auth-enabled deployment

- **WHEN** sign-in starts for `preview-studio-alice.freepod.app` and `studio-alice.freepod.app` is an auth-enabled deployment
- **THEN** the broker proceeds as for `studio-alice.freepod.app`, and issues a code bound to `preview-studio-alice.freepod.app`

#### Scenario: Base deployment without authentication

- **WHEN** sign-in starts for `preview-shop-alice.freepod.app` and `shop-alice.freepod.app` has not enabled authentication
- **THEN** the broker shows an error and issues no code

#### Scenario: Unknown base host

- **WHEN** sign-in starts for `preview-nothing-alice.freepod.app` and no deployment has `nothing-alice.freepod.app`
- **THEN** the broker shows an error and does not redirect

#### Scenario: Preview prefix on a custom domain

- **WHEN** sign-in starts for `preview-shop.example.com` and `shop.example.com` is an auth-enabled deployment's custom domain
- **THEN** the broker shows an error and issues no code

### Requirement: One consent covers a deployment's hostnames

Consent SHALL remain recorded per deployment. A user who has consented on a deployment's hostname SHALL NOT be asked again on its preview hostname, and the reverse.

#### Scenario: Consent carried to the preview

- **WHEN** Alice has consented on `studio-alice.freepod.app` and then signs in on `preview-studio-alice.freepod.app`
- **THEN** she is not asked for consent again

### Requirement: Signing in ties a listed entry to the account

When a person signs in to a `listed` deployment through an unbound entry that matches their verified email, the broker SHALL record their subject and display name on that entry before it issues a code, for either protocol. It SHALL NOT change an entry that is already tied to a subject.

#### Scenario: First sign-in

- **WHEN** `jules@example.org` is listed, unbound, and Jules signs in to the deployment for the first time
- **THEN** the entry holds Jules's subject and name before the code is issued

#### Scenario: Concurrent first sign-ins

- **WHEN** Jules completes sign-in in two browsers at the same moment against the same unbound entry
- **THEN** both sign-ins succeed and the entry is tied to Jules's subject once

#### Scenario: Entry already tied

- **WHEN** an entry is tied to one subject and a different subject signs in with the entry's email
- **THEN** the entry is unchanged and the broker refuses the sign-in
