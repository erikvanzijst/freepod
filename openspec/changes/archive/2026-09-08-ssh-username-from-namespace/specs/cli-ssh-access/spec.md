## ADDED Requirements

### Requirement: The username is the deployment's id, taken from the platform's record
Every SSH connection the client opens MUST present the deployment's id as the username. The client MUST take that identifier from the deployment record the platform returns and MUST NOT construct it from any other field.

The edge admits one identifier and refuses everything else without saying why, so a client that derives a username by its own rule fails as an authentication refusal — the least diagnosable failure the platform produces. Reading the identifier from the record keeps the client correct across any later change to how the platform assigns it, without a client release.

All four commands MUST derive the username the same way, so no subset of them keeps working after a change to the platform's assignment.

#### Scenario: Every command presents the same username
- **WHEN** a user runs the shell, database-forward, database-session, or copy command
- **THEN** each connects with the deployment's id as the username

#### Scenario: The username is not derived from the deployment's other identifiers
- **WHEN** the client assembles a connection
- **THEN** it uses the id from the deployment record, and neither the deployment's name nor its namespace appears in any part of the username

#### Scenario: A stale identifier is not cached across a change
- **WHEN** the platform's record for a deployment reports a username
- **THEN** the client uses that value for the connection it is about to open, rather than one it derived or stored earlier
