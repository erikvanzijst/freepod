# Spec Delta

## ADDED Requirements

### Requirement: Sign-in records

The platform SHALL store one sign-in record per (identity provider session, deployment), holding the identity provider session ID, the deployment, the subject, the `sid` given to the deployment, and the time of the latest sign-in. Records SHALL be deleted with their deployment.

#### Scenario: One record per session and deployment

- **WHEN** a sign-in is recorded twice for the same identity provider session and deployment
- **THEN** exactly one record exists, carrying the later time

#### Scenario: Deployment deleted

- **WHEN** a deployment with sign-in records is deleted
- **THEN** its sign-in records no longer exist

### Requirement: Ended-session records

The platform SHALL store each ended identity provider session once, with its session ID and the time it ended.

#### Scenario: Ended twice

- **WHEN** the same session is recorded as ended twice
- **THEN** exactly one record exists, carrying the first time

## MODIFIED Requirements

### Requirement: Sign-in code records

The platform SHALL store each issued sign-in code only as a one-way hash. Each record SHALL carry the host, subject, email, display name, identity provider session ID, return target, sign-in attempt binding, and expiry. Redeeming a code SHALL remove its record atomically, so two concurrent redemptions of one code cannot both succeed. Expired records SHALL be removed within one hour of expiry.

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

The platform SHALL store each OIDC authorization code the provider issues only as a one-way hash, in records separate from sign-in codes, so that neither kind can be redeemed as the other. Each record SHALL carry the deployment, the redirect URI, the subject, email and display name, the `sid` given to the deployment, the request's nonce and code challenge when given, the time the user authenticated, and the expiry. Redeeming a code SHALL remove its record atomically. Expired records SHALL be removed within one hour of expiry.

#### Scenario: Concurrent redemption

- **WHEN** the same authorization code is redeemed twice at the same moment
- **THEN** exactly one redemption succeeds

#### Scenario: Kinds do not mix

- **WHEN** an OIDC authorization code is presented to an app host's sign-in callback
- **THEN** it is not found

### Requirement: Least-privilege database role

The app authentication service SHALL connect to the platform database as its own role. The role SHALL be able to read only the columns it needs to decide eligibility and access: the deployment's identifier, hostname, status, owner and applied release; that release's template and values; the template's system values; and the owning user's identifier and email. It SHALL read and write only the consent table, the sign-in code table, the OIDC authorization code table, the sign-in record table and the ended-session table. It SHALL read access list entries and update only their subject, display name and binding time. It SHALL NOT be able to write any other table or read any other column. The role SHALL be created and its grants re-applied idempotently on every rollout.

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

#### Scenario: Sign-out records are its own

- **WHEN** the role inserts, reads and deletes sign-in and ended-session records
- **THEN** the database allows it

#### Scenario: The list is the owner's to change

- **WHEN** the role attempts to insert or delete an access list entry, or change its email
- **THEN** the database refuses

#### Scenario: Users' other details are out of reach

- **WHEN** the role attempts to read a user's columns other than the identifier and email
- **THEN** the database refuses
