# app-auth-data-model Specification

## Purpose

The platform records app authentication keeps: per-user, per-deployment consent, the short-lived single-use sign-in codes and OIDC authorization codes, plus the least-privilege database access the app authentication service runs with.

## Requirements

### Requirement: Consent records

The platform SHALL store one consent record per (identity-provider subject, deployment). It SHALL hold the subject, the deployment, the set of identity claims the user agreed to disclose, and the time consent was given. At most one record SHALL exist per pair. Consent records SHALL be keyed by the identity-provider subject, not by a platform user row, because people who sign in to apps need never have used Freepod itself.

#### Scenario: Repeat consent is idempotent

- **WHEN** consent is recorded twice for the same subject and deployment
- **THEN** exactly one record exists

#### Scenario: User without a platform account row

- **WHEN** someone who has never opened the Freepod web app consents to a `custom` app
- **THEN** their consent is recorded without creating a platform user

### Requirement: Sign-in code records

The platform SHALL store each issued sign-in code only as a one-way hash. Each record SHALL carry the host, subject, email, display name, return target, sign-in attempt binding, and expiry. Redeeming a code SHALL remove its record atomically, so two concurrent redemptions of one code cannot both succeed. Expired records SHALL be removed within one hour of expiry.

#### Scenario: Concurrent redemption

- **WHEN** the same code is redeemed twice at the same moment
- **THEN** exactly one redemption succeeds

#### Scenario: Stored codes are not usable

- **WHEN** an operator reads the code table
- **THEN** no stored value can be presented as a code

#### Scenario: Cleanup

- **WHEN** a code expired more than an hour ago
- **THEN** its record no longer exists

### Requirement: OIDC authorization code records

The platform SHALL store each OIDC authorization code the provider issues only as a one-way hash, in records separate from sign-in codes, so that neither kind can be redeemed as the other. Each record SHALL carry the deployment, the redirect URI, the subject, email and display name, the request's nonce and code challenge when given, the time the user authenticated, and the expiry. Redeeming a code SHALL remove its record atomically. Expired records SHALL be removed within one hour of expiry.

#### Scenario: Concurrent redemption

- **WHEN** the same authorization code is redeemed twice at the same moment
- **THEN** exactly one redemption succeeds

#### Scenario: Kinds do not mix

- **WHEN** an OIDC authorization code is presented to an app host's sign-in callback
- **THEN** it is not found

### Requirement: Least-privilege database role

The app authentication service SHALL connect to the platform database as its own role. The role SHALL be able to read only the columns it needs to decide eligibility and access: the deployment's identifier, hostname, status, owner and applied release; that release's template and values; the template's system values; and the owning user's identifier and email. It SHALL read and write only the consent table, the sign-in code table and the OIDC authorization code table. It SHALL read access list entries and update only their subject, display name and binding time. It SHALL NOT be able to write any other table or read any other column. The role SHALL be created and its grants re-applied idempotently on every rollout.

#### Scenario: Service bug cannot write deployments

- **WHEN** the app authentication service's role attempts to update a deployment row
- **THEN** the database refuses

#### Scenario: Secrets are out of reach

- **WHEN** the role attempts to read encrypted var values or database passwords
- **THEN** the database refuses

#### Scenario: Products are out of reach

- **WHEN** the role attempts to read the product table
- **THEN** the database refuses

#### Scenario: OIDC codes are its own

- **WHEN** the role inserts, reads and deletes an OIDC authorization code record
- **THEN** the database allows it

#### Scenario: The list is the owner's to change

- **WHEN** the role attempts to insert or delete an access list entry, or change its email
- **THEN** the database refuses

#### Scenario: Users' other details are out of reach

- **WHEN** the role attempts to read a user's columns other than the identifier and email
- **THEN** the database refuses

### Requirement: Access list entry records

The platform SHALL store each access list entry with its deployment, the email in lower case, the time it was added, and, once bound, the subject, the display name and the time it was bound. A deployment SHALL hold at most one entry per email and at most one per subject. Entries SHALL be deleted with their deployment.

#### Scenario: One entry per email

- **WHEN** a second entry with the same email is inserted for a deployment
- **THEN** the database refuses it

#### Scenario: One entry per subject

- **WHEN** a second entry of a deployment is bound to a subject another entry already holds
- **THEN** the database refuses it

### Requirement: Invitation records

The platform SHALL record each invitation it sends, with the inviting owner and the time it was sent, independently of the entry, so that removing an entry does not erase it. Records older than seven days SHALL be removed. They SHALL be deleted with the owner's account.

#### Scenario: Entry removed

- **WHEN** an owner removes an entry they added an hour ago
- **THEN** the invitation sent for it is still recorded
