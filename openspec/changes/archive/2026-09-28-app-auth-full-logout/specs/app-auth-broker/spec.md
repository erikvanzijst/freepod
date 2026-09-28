## ADDED Requirements

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
