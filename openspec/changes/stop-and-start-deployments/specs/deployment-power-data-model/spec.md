## Purpose

How a deployment's power is recorded: whether its workloads are running, paused or stopped. It covers an append-only ledger of power changes, the desired and applied pointers on the deployment, and what deployment reads expose of it.

## ADDED Requirements

### Requirement: Power changes are recorded as append-only rows

Every power change SHALL be recorded as a new row in a power ledger. A row SHALL record the deployment, the requested state, the reason, the acting user (null for the platform) and when it was requested. A row SHALL NOT be deleted or have its request fields rewritten.

#### Scenario: Stopping records a row

- **WHEN** an owner stops a running deployment
- **THEN** a new power row records state `stopped`, reason `manual`, the owner as actor, and the time of the request

#### Scenario: Starting records a further row

- **WHEN** the owner later starts it
- **THEN** a second row records state `running` with reason `manual`
- **AND** the first row is unchanged

### Requirement: Power has three states

A power row's state SHALL be one of `running`, `paused` and `stopped`, enforced by the database. `paused` means the app is not running and a visitor's request starts it. `stopped` means the app is not running and only an explicit start runs it again. No separate flag SHALL qualify a state.

#### Scenario: An unknown state is rejected

- **WHEN** a power row is written with a state outside the set
- **THEN** the database rejects the write

### Requirement: The reason is one of a closed set

A power row's reason SHALL be one of `manual`, `idle`, `payment`, `traffic` and `release`, enforced by the database. Reasons that no component produces yet SHALL still be accepted by the schema, so that later phases add producers without a migration.

#### Scenario: An unknown reason is rejected

- **WHEN** a power row is written with a reason outside the set
- **THEN** the database rejects the write

### Requirement: The reconciler records each power row's outcome once

A power row's outcome, when work began, when it ended and any error, SHALL be written by the reconciler. The start time SHALL be written only if not already set, so that a re-run after a worker died records when work first began. The end time and error SHALL be written once.

#### Scenario: A stop is applied

- **WHEN** the reconciler applies a stop successfully
- **THEN** the power row records when work began and when it ended, with no error

#### Scenario: A stop fails

- **WHEN** the reconcile applying a stop fails
- **THEN** the power row records when it ended and why

### Requirement: The deployment points at its desired and applied power

A deployment SHALL carry two nullable references into the power ledger: the power it desires and the power it is running. A null reference SHALL mean `running`, so that a deployment that was never stopped or paused needs no power row. A power change SHALL move only the desired reference; only a successful reconcile SHALL move the applied reference to the desired one.

#### Scenario: A deployment that was never stopped

- **WHEN** a deployment has no power rows
- **THEN** both references are null and the deployment reads as running

#### Scenario: A stop in flight

- **WHEN** a stop has been requested and its reconcile has not finished
- **THEN** the desired reference names the `stopped` row and the applied reference is unchanged

#### Scenario: A failed power change leaves the applied power

- **WHEN** the reconcile applying a power change fails
- **THEN** the applied reference is unchanged, because the atomic rollback restored the previous power

### Requirement: Existing deployments are running without a backfill

Adding power SHALL NOT require writing a row for any existing deployment. Every deployment that exists when the ledger is introduced SHALL read as running.

#### Scenario: After the migration

- **WHEN** the migration that introduces the power ledger has run
- **THEN** no power rows exist and every existing deployment reads as running

### Requirement: Deployment reads expose desired and applied power

Every deployment read, single and listed, SHALL include a `power` object with the desired state, the applied state, and the desired row's reason (null when the desired state is `running`). It SHALL be readable across a listing without a query per deployment.

#### Scenario: A stopped deployment

- **WHEN** a deployment its owner stopped has been applied
- **THEN** its read reports desired `stopped`, applied `stopped` and reason `manual`

#### Scenario: A deployment that is stopping

- **WHEN** a stop has been requested but not yet applied
- **THEN** its read reports desired `stopped` and applied `running`

#### Scenario: A running deployment

- **WHEN** a deployment has never been stopped, or has been started again and the start applied
- **THEN** its read reports desired `running` and applied `running`, with no reason

### Requirement: Power rows are removed with their deployment

Power rows SHALL belong to exactly one deployment and SHALL be removed when that deployment's row is removed.

#### Scenario: A deployment is purged

- **WHEN** a deployment row is deleted
- **THEN** its power rows are deleted with it
