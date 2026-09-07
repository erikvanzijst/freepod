## ADDED Requirements

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

### Requirement: Grafana login names derive from the same value

Grafana resolves its login name from the `preferred_username` claim, so normalizing usernames
changes the login name shown for every affected Grafana user. Before the pass runs, it SHALL
be established that Grafana matches a returning user by the token subject rather than by
login name, so that an affected user is renamed rather than issued a second Grafana account.

#### Scenario: An affected Grafana user keeps one account

- **WHEN** a user in the observability group signs in to Grafana after normalization
- **THEN** they reach their existing Grafana account under a changed login name, and no
  second account is created for them
