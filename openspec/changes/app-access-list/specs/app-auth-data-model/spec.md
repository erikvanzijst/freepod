# Spec Delta

## ADDED Requirements

### Requirement: Access list entry records

The platform SHALL store each access list entry with its deployment, the email in lower case, the time it was added, and, once bound, the subject, the display name and the time it was bound. A deployment SHALL hold at most one entry per email and at most one per subject. Entries SHALL be deleted with their deployment.

#### Scenario: One entry per email

- **WHEN** a second entry with the same email is inserted for a deployment
- **THEN** the database refuses it

#### Scenario: One entry per subject

- **WHEN** a second entry of a deployment is bound to a subject another entry already holds
- **THEN** the database refuses it

### Requirement: Logout outbox records

Removing a bound entry SHALL record, in the same transaction, the deployment and subject a logout token is owed for, with the time it was recorded and its delivery attempts. A record SHALL be removed once its token is delivered, refused by the app, or no longer deliverable, and in any case within 24 hours. Records SHALL be deleted with their deployment.

#### Scenario: Removal and record together

- **WHEN** the removal of a bound entry fails to commit
- **THEN** no logout record exists for it, and the entry is still on the list

### Requirement: Invitation records

The platform SHALL record each invitation it sends, with the inviting owner and the time it was sent, independently of the entry, so that removing an entry does not erase it. Records older than seven days SHALL be removed. They SHALL be deleted with the owner's account.

#### Scenario: Entry removed

- **WHEN** an owner removes an entry they added an hour ago
- **THEN** the invitation sent for it is still recorded

## MODIFIED Requirements

### Requirement: Least-privilege database role

The app authentication service SHALL connect to the platform database as its own role. The role SHALL be able to read only the columns it needs to decide eligibility and access: the deployment's identifier, hostname, status, owner and applied release; that release's template and values; the template's system values; and the owning user's identifier and email. It SHALL read and write only the consent table, the sign-in code table and the OIDC authorization code table. It SHALL read access list entries and update only their subject, display name and binding time, and SHALL read, update and delete logout outbox records. It SHALL NOT be able to write any other table or read any other column. The role SHALL be created and its grants re-applied idempotently on every rollout.

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
