# Spec Delta

## Purpose

Defines a user's identifier: how it is assigned, what it looks like, how ids issued before it carry over, and which externally visible names are derived from it. The identifier exists to reference an account without revealing how many accounts exist or the order they were created in.

## ADDED Requirements

### Requirement: A new account's identifier is random and opaque
The platform SHALL assign each new account an identifier of exactly 12 characters drawn uniformly at random from lowercase letters and digits (`[0-9a-z]`), using a cryptographically secure source. The identifier SHALL be assigned when the account is created, and SHALL NOT be derived from a sequence, a timestamp, the email address, or any other attribute of the account.

#### Scenario: Account created on first sign-in
- **WHEN** a person signs in for the first time and an account is created for them
- **THEN** the account's identifier is 12 characters of `[0-9a-z]`

#### Scenario: Consecutive accounts reveal no ordering
- **WHEN** two accounts are created one after the other
- **THEN** neither identifier can be computed from the other, and comparing them does not reveal which account was created first

#### Scenario: Operator-created account
- **WHEN** an operator creates an account through the operator CLI
- **THEN** it receives an identifier under the same rule as a self-service sign-up

### Requirement: A new identifier is never all digits
A newly assigned identifier SHALL contain at least one letter. Every identifier issued before this capability was decimal digits, so an all-digit new identifier could collide with one of those, and it would read as a sequence number.

#### Scenario: Generated value is all digits
- **WHEN** the random draw produces 12 digits
- **THEN** that value is discarded and a new one is drawn

### Requirement: Existing accounts keep their identifier
An account that existed before this capability SHALL keep its previous number as its identifier, written as decimal text with no padding (account `42` becomes `"42"`). No existing account SHALL be issued a new identifier.

#### Scenario: Existing account after the upgrade
- **WHEN** account 42 calls `GET /api/me` after the upgrade
- **THEN** the response's `id` is the string `"42"`

#### Scenario: Existing paths keep resolving
- **WHEN** account 42 requests `/api/users/42/deployments` after the upgrade
- **THEN** the request is authorized and served exactly as before

### Requirement: The database enforces uniqueness and format only
The database SHALL NOT generate user identifiers. It SHALL reject a user row whose identifier is empty, longer than 12 characters, contains a character outside `[0-9a-z]`, or duplicates an existing identifier. Every column that references a user SHALL hold the same identifier type and stay enforced as a foreign key.

#### Scenario: Insert without an identifier
- **WHEN** a user row is inserted with no identifier
- **THEN** the database rejects the insert

#### Scenario: Insert with an invalid identifier
- **WHEN** a user row is inserted with an identifier containing an uppercase letter, or of 13 characters
- **THEN** the database rejects the insert

#### Scenario: Duplicate identifier
- **WHEN** a user row is inserted with an identifier that another row already holds
- **THEN** the database rejects the insert

### Requirement: The API carries user identifiers as strings
Every user identifier the API accepts or returns SHALL be a string. This covers the `user_id` path parameter, `id` on user representations including `/api/me`, `user_id` on deployment, subscription and usage representations, and the admin `user_id` usage filter. An identifier SHALL be matched exactly, with no numeric interpretation.

#### Scenario: Identifier in a response
- **WHEN** a client reads a deployment
- **THEN** its `user_id` is a JSON string

#### Scenario: No numeric normalization
- **WHEN** account `"42"` requests `/api/users/042/deployments`
- **THEN** the path does not identify account `"42"`, and the request is refused like a request for any other account

#### Scenario: Admin filters usage by a new account
- **WHEN** an administrator requests usage filtered by `user_id=k7m2qx9d4hfa`
- **THEN** the report covers that account only

### Requirement: Names derived from a user identifier use it verbatim
The owner's image repository (`u/{id}`), registry pull username (`pull-{id}`), pull credential, build image reference (`{id}@{digest}`) and artifact object keys SHALL embed the identifier text verbatim. For an account that existed before this capability, each derived name SHALL be byte-identical to what it was before.

#### Scenario: Existing account's images survive the upgrade
- **WHEN** account `"42"`'s deployment pulls an image built before the upgrade
- **THEN** the image is still at `u/42`, and the previously published pull credential still authenticates

#### Scenario: New account's repository
- **WHEN** account `"k7m2qx9d4hfa"` completes a build
- **THEN** the image is pushed to `u/k7m2qx9d4hfa` and the build's `image` is `k7m2qx9d4hfa@sha256:<digest>`

#### Scenario: Pull username for an unknown identifier
- **WHEN** the registry token endpoint is presented a pull username whose identifier matches no live account
- **THEN** the credential is refused, as before
