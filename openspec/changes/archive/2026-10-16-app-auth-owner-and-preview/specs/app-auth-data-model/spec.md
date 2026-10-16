# Spec Delta

## MODIFIED Requirements

### Requirement: Least-privilege database role

The app authentication service SHALL connect to the platform database as its own role. The role SHALL be able to read only the columns it needs to decide eligibility: the deployment's identifier, hostname, status and applied release; that release's template and values; and the template's system values. It SHALL read and write only the consent and code tables. It SHALL NOT be able to write any other table or read any other column. The role SHALL be created and its grants re-applied idempotently on every rollout.

#### Scenario: Service bug cannot write deployments

- **WHEN** the app authentication service's role attempts to update a deployment row
- **THEN** the database refuses

#### Scenario: Secrets are out of reach

- **WHEN** the role attempts to read encrypted var values or database passwords
- **THEN** the database refuses

#### Scenario: Products are out of reach

- **WHEN** the role attempts to read the product table
- **THEN** the database refuses
