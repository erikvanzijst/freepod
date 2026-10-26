# Spec Delta

## ADDED Requirements

### Requirement: OIDC authorization code records

The platform SHALL store each OIDC authorization code the provider issues only as a one-way hash, in records separate from sign-in codes, so that neither kind can be redeemed as the other. Each record SHALL carry the deployment, the redirect URI, the subject, email and display name, the request's nonce and code challenge when given, the time the user authenticated, and the expiry. Redeeming a code SHALL remove its record atomically. Expired records SHALL be removed within one hour of expiry.

#### Scenario: Concurrent redemption

- **WHEN** the same authorization code is redeemed twice at the same moment
- **THEN** exactly one redemption succeeds

#### Scenario: Kinds do not mix

- **WHEN** an OIDC authorization code is presented to an app host's sign-in callback
- **THEN** it is not found

## MODIFIED Requirements

### Requirement: Least-privilege database role

The app authentication service SHALL connect to the platform database as its own role. The role SHALL be able to read only the columns it needs to decide eligibility: the deployment's identifier, hostname, status and applied release; that release's template and values; and the template's system values. It SHALL read and write only the consent table, the sign-in code table and the OIDC authorization code table. It SHALL NOT be able to write any other table or read any other column. The role SHALL be created and its grants re-applied idempotently on every rollout.

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
