## ADDED Requirements

### Requirement: A power change is not a release

Stopping or starting a deployment SHALL NOT create a release. A reconcile whose desired release is already the deployment's applied release SHALL apply the deployment's desired power without claiming that release, and SHALL write none of its columns. A power change's outcome SHALL be recorded in the power ledger instead.

#### Scenario: Stopping a deployment

- **WHEN** a running deployment is stopped and the reconcile succeeds
- **THEN** no release is created
- **AND** no column of the applied release is modified

#### Scenario: A power reconcile fails

- **WHEN** a reconcile that only changes power fails and Helm rolls back
- **THEN** no release records the failure, and the applied release is unchanged

#### Scenario: A rollout to a stopped deployment

- **WHEN** a stopped deployment is updated
- **THEN** exactly one release is created, as for any update, and its outcome is recorded on it
