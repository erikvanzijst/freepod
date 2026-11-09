# Spec Delta

## MODIFIED Requirements

### Requirement: Least-privilege database role

The app authentication service SHALL connect to the platform database as its own role. The role SHALL be able to read only the columns it needs to decide eligibility and access: the deployment's identifier, hostname, status, owner and applied release; that release's template and values; the template's system values; and the owning user's identifier, email and subject. It SHALL read and write only the consent table, the sign-in code table, the OIDC authorization code table, the sign-in record table and the ended-session table. It SHALL read access list entries and update only their subject, display name and binding time. It SHALL be able to queue notifications through the producer columns of the notification outbox, and SHALL NOT be able to read or change queued notifications. It SHALL NOT be able to write any other table or read any other column. The role SHALL be created and its grants re-applied idempotently on every rollout.

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

- **WHEN** the role attempts to read a user's columns other than the identifier, email and subject
- **THEN** the database refuses

#### Scenario: Notifications are queue-only

- **WHEN** the role queues a notification, and then attempts to read it or change its state
- **THEN** the queueing is allowed and the read and the change are refused
