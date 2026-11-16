# Spec Delta

## MODIFIED Requirements

### Requirement: The deployment pointer is discarded once the platform accepts the deletion

The client SHALL remove the deployment pointer from the project file as soon as the
platform accepts the deletion, and SHALL do so before waiting for the teardown to
finish. From that moment the deployment can never serve the project again, so retaining
the pointer would only make the next deploy fail against something the user has already
asked to be rid of — and an interrupted wait must not leave the pointer behind.

The pointer SHALL be removed by deleting the `deployment` key, leaving the project
unlinked. Every other key in the project file SHALL be retained. They are the
developer's intent rather than the deployment's state, so `freepod init` in the
unlinked project SHALL create a new deployment and apply them to it.

Where the platform refuses the deletion, the pointer SHALL be retained, because it still
describes a deployment that exists.

#### Scenario: A successful deletion clears only the pointer

- **WHEN** the platform accepts the deletion
- **THEN** the project file has no `deployment` key
- **AND** its other keys are unchanged

#### Scenario: The pointer is cleared before the teardown is awaited

- **WHEN** the platform accepts the deletion and the subsequent wait does not complete
- **THEN** the project file no longer records a deployment

#### Scenario: A refused deletion keeps the pointer

- **WHEN** the platform refuses the deletion
- **THEN** the project file still records the deployment
