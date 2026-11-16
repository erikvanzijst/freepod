# Spec Delta

## MODIFIED Requirements

### Requirement: Column rename from deployment_uid to name
The generated release name MUST stay in the `name` column of the `deployment` table, and code MUST reference it as `deployment.name`. Deployment reads MUST NOT report it: the `name` field of a read is the owner-chosen name of deployment-identity, stored in its own column.

#### Scenario: API response uses name field
- **WHEN** a client reads a deployment via the API
- **THEN** the response's `name` field is the owner-chosen name
- **AND** the response does not include the generated release name under any field

#### Scenario: ORM model uses name field
- **WHEN** application code accesses the deployment's release name
- **THEN** it uses `deployment.name`, and the owner-chosen name is a separate attribute
