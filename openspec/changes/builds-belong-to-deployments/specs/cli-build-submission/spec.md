## MODIFIED Requirements

### Requirement: A build is created from the uploaded artifact

The client SHALL create a build for the project's recorded deployment, referencing the
uploaded artifact identifier and supplying that identifier alone. It SHALL NOT attempt to
specify the build's owner, which is the deployment's.

#### Scenario: A build is queued

- **WHEN** the client creates a build for a successfully uploaded artifact
- **THEN** the platform returns a build in a queued state, belonging to the project's deployment
