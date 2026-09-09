# keycloak-user-realm Specification

## Purpose
Define the dedicated `freepod` Keycloak realm that Freepod end users
authenticate against, separate from the built-in `master` administrative
realm: its registration and email-verification policy, SMTP, themes, the
per-environment OAuth2 clients, and the groups that gate access to the
development environment and to Grafana.

Social identity providers are deliberately **not** part of this capability.
Google, Apple and Microsoft were specified here for a long time and never
built, and a spec asserting infrastructure that does not exist is how the
`master`-realm drift went unnoticed. Propose them as their own change if they
are ever wanted.
## Requirements
### Requirement: Keycloak has a Freepod realm
The system SHALL authenticate Freepod end users against a dedicated Keycloak
realm named `freepod`. End-user accounts SHALL NOT be created in the built-in
`master` realm, which is Keycloak's administrative realm and governs the whole
instance.

#### Scenario: Freepod realm exists
- **WHEN** Keycloak admin API is queried for realms
- **THEN** a realm named `freepod` exists

#### Scenario: Realm discovery document is reachable
- **WHEN** `https://keycloak.freepod.eu/realms/freepod/.well-known/openid-configuration`
  is requested
- **THEN** it returns a valid OIDC discovery document whose `issuer` is
  `https://keycloak.freepod.eu/realms/freepod`

#### Scenario: End users are not created in master
- **WHEN** a user self-registers through Freepod
- **THEN** the account is created in the `freepod` realm
- **AND** no account is created in the `master` realm

### Requirement: Local user registration is enabled
The system SHALL enable self-registration in the `freepod` realm, because
Freepod is a public service that accepts sign-ups from anyone.

#### Scenario: Self-registration is enabled
- **WHEN** the `freepod` realm settings are inspected
- **THEN** `registrationAllowed` is set to `true`

#### Scenario: Registration is not restricted per environment
- **WHEN** an operator seeks to close registration for one environment only
- **THEN** it is understood that `registrationAllowed` is a realm-level setting
  with no per-client equivalent
- **AND** per-environment restriction is achieved through group-based
  authorization instead

### Requirement: Registration does not collect a username

The `freepod` realm SHALL set `registrationEmailAsUsername`, so that a self-registering
user's username is their email address and no username field appears on the registration
form.

Nothing in Freepod reads a Keycloak username: callers are resolved by email, and no Keycloak
identifier is persisted. A required, uniqueness-checked field with no consumer is a second
way for registration to fail, on a form that reports failures only on submit and clears the
password fields when it does.

#### Scenario: The setting is enabled on the realm

- **WHEN** the `freepod` realm settings are inspected
- **THEN** `registrationEmailAsUsername` is `true`

#### Scenario: The registration form asks for no username

- **WHEN** a prospective user opens the registration form
- **THEN** it presents no username field

#### Scenario: A new account's username is its email address

- **WHEN** a user self-registers with the address `ada@example.com`
- **THEN** the account's username is `ada@example.com`

### Requirement: The settings this depends on are pinned

The `freepod` realm SHALL keep `duplicateEmailsAllowed` false and `editUsernameAllowed`
false for as long as the username is derived from the email address.

Neither is incidental. Keycloak rejects the combination of duplicate emails with
email-as-username, and it does not permit a self-editable username alongside it — so
enabling either silently breaks registration or the setting above, rather than adding an
option.

#### Scenario: Duplicate emails remain disallowed

- **WHEN** the realm settings are inspected
- **THEN** `duplicateEmailsAllowed` is `false`

#### Scenario: Self-service username editing remains disabled

- **WHEN** the realm settings are inspected
- **THEN** `editUsernameAllowed` is `false`

#### Scenario: Login by email is unaffected

- **WHEN** any user signs in with their email address and password
- **THEN** authentication succeeds as before

### Requirement: Existing usernames are normalized in one deliberate pass

When the setting is enabled, every pre-existing account whose username is not already its
email address SHALL be updated to match, in one operator-run pass at the time of the change,
through the Keycloak admin API rather than through Terraform.

Keycloak does not leave those accounts alone: with the setting on, the next update to such an
account — by the user or by an administrator — overwrites the custom username with the email
address. Left to happen on its own, that is an unannounced change to a person's credential
at an unpredictable moment, and it lands one account at a time with no record of which have
converted. Doing it deliberately makes it one event with a known scope.

Terraform SHALL NOT perform this pass, because it does not manage end-user accounts.

#### Scenario: No account is left with a divergent username

- **WHEN** the pass has completed
- **THEN** every non-deleted account's username equals its email address

#### Scenario: The pass runs through the admin API

- **WHEN** usernames are normalized
- **THEN** the updates are made through the Keycloak admin API, and no end-user account is
  represented in Terraform state

#### Scenario: An affected user can still sign in

- **WHEN** a user whose username was normalized signs in afterwards
- **THEN** their email address and existing password authenticate them, and no password
  reset is required

### Requirement: Email verification is required
The system SHALL require email verification for new user accounts in the
`freepod` realm. Because the email claim is the sole join key between Keycloak
and Freepod's own user records, an unverified email is a privilege-escalation
vector and verification SHALL NOT be relaxed.

#### Scenario: Email verification is required
- **WHEN** the `freepod` realm settings are inspected
- **THEN** `verifyEmail` is set to `true`

#### Scenario: Email is the identity join key
- **WHEN** Freepod resolves an authenticated caller to a user record
- **THEN** the lookup is performed on the verified email claim
- **AND** no Keycloak subject identifier is persisted by Freepod

### Requirement: SMTP is configured for email sending
The system SHALL configure SMTP on the `freepod` realm through Terraform, so
that email verification and self-service password reset both function. A realm
without SMTP fails these flows silently.

#### Scenario: SMTP is configured
- **WHEN** the `freepod` realm SMTP settings are inspected
- **THEN** host, port, from address, and credentials are configured
- **AND** the values are supplied from Terraform variables, not entered by hand

#### Scenario: Password reset is self-service
- **WHEN** a user without a credential requests a password reset from the login
  page
- **THEN** `resetPasswordAllowed` is enabled on the realm
- **AND** Keycloak emails an action-token link that allows the user to set a
  password

### Requirement: Per-environment OAuth2 proxy clients are configured
The system SHALL create one Keycloak client per Freepod environment in the
`freepod` realm: `freepod-prod` for `freepod.eu` and `freepod-dev` for
`dev.freepod.eu`. A single client SHALL NOT serve both environments, so that a
session or token issued for one environment is not interchangeable with the
other.

#### Scenario: Both environment clients exist
- **WHEN** Keycloak clients are listed for realm `freepod`
- **THEN** clients with client IDs `freepod-prod` and `freepod-dev` exist
- **AND** each client protocol is `openid-connect`
- **AND** each access type is `confidential`

#### Scenario: Redirect URIs are scoped to one host each
- **WHEN** the `freepod-prod` client is inspected
- **THEN** its valid redirect URIs reference only `freepod.eu`
- **WHEN** the `freepod-dev` client is inspected
- **THEN** its valid redirect URIs reference only `dev.freepod.eu`

#### Scenario: Unnecessary grants are disabled
- **WHEN** either environment client is inspected
- **THEN** `directAccessGrantsEnabled` is `false`, because the browser flow does
  not use the resource owner password credentials grant
- **AND** PKCE is required with challenge method `S256`

### Requirement: Client scopes map email and groups claims
The system SHALL assign the client scopes needed for both identity and
authorization to each environment client. The `email` scope carries the identity
that Freepod resolves users by; the `groups` scope carries the membership that
per-environment access gating depends on.

#### Scenario: Email scope is assigned
- **WHEN** the client scopes of `freepod-prod` and `freepod-dev` are inspected
- **THEN** the `email` scope is assigned as a default client scope on each

#### Scenario: Groups scope is assigned
- **WHEN** the client scopes of `freepod-prod` and `freepod-dev` are inspected
- **THEN** the `groups` scope is assigned as a default client scope on each
- **AND** an access token issued to either client carries a `groups` claim

#### Scenario: Group claim carries bare names
- **WHEN** the realm's group membership protocol mapper is inspected
- **THEN** `full.path` is `false`, so the claim carries bare group names such as
  `freepod-dev` rather than paths such as `/freepod-dev`

### Requirement: Freepod theme is applied to the realm
The system SHALL configure the `freepod` realm to use the `freepod` login, email
and account themes, so that migrated and new users see Freepod branding rather
than stock Keycloak.

#### Scenario: Themes are set
- **WHEN** the `freepod` realm settings are inspected
- **THEN** `loginTheme`, `emailTheme` and `accountTheme` are each set to
  `freepod`

### Requirement: A dev access group governs the development environment
The system SHALL define a Keycloak group named `freepod-dev` in the `freepod`
realm whose membership determines who may access `dev.freepod.eu`. Membership
SHALL be the sole administrative control for granting and revoking development
access.

#### Scenario: Group exists
- **WHEN** groups are listed for realm `freepod`
- **THEN** a group named `freepod-dev` exists

#### Scenario: Access is granted by group membership
- **WHEN** an operator needs to grant or revoke a user's access to
  `dev.freepod.eu`
- **THEN** it is done by adding or removing that user from the `freepod-dev`
  group
- **AND** no Terraform apply and no second user account are required

### Requirement: The observability group is hosted in the Freepod realm
The system SHALL define the `freepod-observability` group in the `freepod` realm
so that Grafana access is governed by the same user database as Freepod itself,
requiring no separate account.

#### Scenario: Group exists in the Freepod realm
- **WHEN** groups are listed for realm `freepod`
- **THEN** a group named `freepod-observability` exists

#### Scenario: One account serves both Freepod and Grafana
- **WHEN** a user holds membership of both `freepod-dev` and
  `freepod-observability`
- **THEN** the same single account authenticates them to Freepod and to Grafana

### Requirement: Grafana login names derive from the same value

Grafana resolves its login name from the `preferred_username` claim, so normalizing usernames
changes the login name shown for every affected Grafana user. Before the pass runs, it SHALL
be established that Grafana matches a returning user by the token subject rather than by
login name, so that an affected user is renamed rather than issued a second Grafana account.

#### Scenario: An affected Grafana user keeps one account

- **WHEN** a user in the observability group signs in to Grafana after normalization
- **THEN** they reach their existing Grafana account under a changed login name, and no
  second account is created for them

### Requirement: Migrated accounts are seeded with a verified, enabled identity
When seeding the existing accounts into the `freepod` realm, the system SHALL
create each user with a verified email and enabled status, SHALL NOT set an
`UPDATE_PASSWORD` required action, and SHALL NOT migrate role mappings. An
account seeded without a credential obtains a password through the self-service
reset flow.

#### Scenario: Seeded account shape
- **WHEN** a migrated account is created in the `freepod` realm
- **THEN** `emailVerified` is `true` and `enabled` is `true`
- **AND** `requiredActions` is empty

#### Scenario: Required actions would lock the account out
- **WHEN** an operator considers setting `requiredActions: ["UPDATE_PASSWORD"]`
  on a credential-less account
- **THEN** it is understood that required actions execute only after successful
  authentication
- **AND** such an account could never reach the action and would be locked out

#### Scenario: Role mappings are not carried over
- **WHEN** a migrated account is created in the `freepod` realm
- **THEN** no role mapping from the `master` realm is applied
- **AND** in particular the `master` realm `admin` role is not granted, since an
  end-user account holding instance-wide administrative rights is the privilege
  concern this migration resolves

#### Scenario: User sets their own password
- **WHEN** a migrated user without a credential requests a password reset from
  the login page
- **THEN** Keycloak emails an action-token link
- **AND** the user sets a password and can sign in

### Requirement: Password hash carry-over is optional and confined to seeding
Password-hash carry-over SHALL be optional per user, and when exercised SHALL be
performed during seeding, through the Keycloak admin API, gated on verifying one
account before any further account receives a credential. Carrying a hash over
spares the user a password reset; omitting it leaves them the self-service reset
flow.

#### Scenario: Carried credential authenticates unchanged
- **WHEN** an account is seeded with its exported `secretData` and
  `credentialData`
- **THEN** the user signs in with their pre-migration password
- **AND** no password reset is required of them

#### Scenario: One account gates the rest
- **WHEN** hash carry-over is attempted
- **THEN** exactly one account is seeded with its credential and verified to
  sign in before any further account is seeded with a credential
- **AND** on failure the remaining accounts are seeded without credentials and
  use the self-service reset flow

#### Scenario: Carry-over is per user and optional
- **WHEN** an operator chooses to carry hashes for some accounts and not others
- **THEN** each account is seeded independently
- **AND** accounts seeded without a credential remain fully usable through
  self-service reset

#### Scenario: Carry-over happens only during seeding
- **WHEN** cutover has completed and users have begun resetting passwords
- **THEN** hash carry-over is not performed, because writing an exported
  credential at that point would silently revert a password the user has already
  changed

#### Scenario: Credentials are written through the admin API
- **WHEN** a credential is carried over
- **THEN** it is written using the Keycloak admin API rather than by direct SQL,
  so that the Infinispan `users` cache is invalidated correctly and no
  `credential` row is hand-assembled

### Requirement: The master realm is retained then decommissioned for end users
The system SHALL leave the `master` realm intact, including its original
credentials, for a soak period after cutover so that it serves as the rollback
path. After the soak period, self-registration SHALL be disabled on `master` and
the migrated end-user accounts removed.

#### Scenario: Rollback remains available during soak
- **WHEN** a problem is discovered after cutover but during the soak period
- **THEN** reverting the issuer configuration restores working authentication
- **AND** users sign in with their pre-migration credentials with no data
  reconstruction

#### Scenario: Registration is closed on master after soak
- **WHEN** the soak period has elapsed
- **THEN** `registrationAllowed` is `false` on the `master` realm
- **AND** the migrated end-user accounts have been deleted from `master`

#### Scenario: The instance administrator remains in master
- **WHEN** end-user accounts are removed from `master`
- **THEN** the `admin` account is retained, because it is the Keycloak instance
  administrator and must reside in the administrative realm

### Requirement: Per-environment public CLI clients are configured

The system SHALL create one public Keycloak client per Freepod environment in
the `freepod` realm for non-browser API clients: `freepod-cli-prod` for
`freepod.eu` and `freepod-cli-dev` for `dev.freepod.eu`. These clients SHALL be
public rather than confidential, because software distributed to end users
cannot hold a client secret.

The one-client-per-environment rule that governs the oauth2-proxy clients
applies here for the same reason: a token issued for one environment must not be
usable against the other. Both CLI clients register identical loopback redirect
URIs, so the token audience is the only thing that separates them.

#### Scenario: Both CLI clients exist
- **WHEN** Keycloak clients are listed for realm `freepod`
- **THEN** clients with client IDs `freepod-cli-prod` and `freepod-cli-dev`
  exist
- **AND** each client protocol is `openid-connect`
- **AND** each access type is `public`

#### Scenario: Loopback redirect URIs are registered
- **WHEN** either CLI client is inspected
- **THEN** its valid redirect URIs are loopback addresses registered without a
  port, so that a client binding an ephemeral port matches
- **AND** no redirect URI references a public hostname

#### Scenario: Grants are limited to the two supported flows
- **WHEN** either CLI client is inspected
- **THEN** the standard flow is enabled and PKCE is required with challenge
  method `S256`
- **AND** the OAuth 2.0 Device Authorization Grant is enabled
- **AND** `directAccessGrantsEnabled` is `false`
- **AND** `serviceAccountsEnabled` is `false`

#### Scenario: CLI clients are distinct from the proxy clients
- **WHEN** the realm's clients are compared
- **THEN** `freepod-cli-prod` and `freepod-cli-dev` are separate from
  `freepod-prod` and `freepod-dev`
- **AND** the oauth2-proxy clients remain confidential

### Requirement: Audience client scopes bind a token to one environment

The system SHALL declare one audience client scope per environment, assigned as
a default scope to that environment's CLI client, whose audience protocol mapper
adds the environment's oauth2-proxy client ID to the `aud` claim of issued
access tokens.

This exists because Keycloak's default access token carries `aud: ["account"]`
and records the requesting client only in `azp`, which the edge's audience
verification does not accept. The scope is therefore load-bearing for
authentication, not a convenience.

#### Scenario: Audience scopes exist
- **WHEN** client scopes are listed for realm `freepod`
- **THEN** an audience scope for the production environment exists whose mapper
  adds `freepod-prod`
- **AND** an audience scope for the development environment exists whose mapper
  adds `freepod-dev`

#### Scenario: Each CLI client gets only its own audience scope
- **WHEN** the default client scopes of `freepod-cli-prod` are inspected
- **THEN** the production audience scope is assigned
- **AND** the development audience scope is not assigned
- **WHEN** the default client scopes of `freepod-cli-dev` are inspected
- **THEN** the development audience scope is assigned
- **AND** the production audience scope is not assigned

#### Scenario: Issued tokens name a single environment
- **WHEN** an access token issued to either CLI client is decoded
- **THEN** its `aud` claim contains exactly one Freepod environment client ID

### Requirement: CLI clients carry the identity and membership scopes

The system SHALL assign the `email` and `groups` client scopes to both CLI
clients, so that tokens issued to them carry the claim Freepod resolves users by
and the claim that per-environment access gating depends on. Omitting `groups`
would deny every CLI request on the gated development environment.

#### Scenario: Email and groups scopes are assigned
- **WHEN** the client scopes of either CLI client are inspected
- **THEN** the `email` scope is assigned as a default client scope
- **AND** the `groups` scope is assigned as a default client scope

#### Scenario: Offline access is available
- **WHEN** the client scopes of either CLI client are inspected
- **THEN** `offline_access` is available to be requested, so a client can obtain
  a durable refresh token

