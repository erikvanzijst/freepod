## Purpose

How a deployment's power is recorded: whether its workloads run or are stopped. It covers an append-only ledger of power changes, the desired and applied pointers on the deployment, and what deployment reads expose of it.

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

### Requirement: Power has two states

A power row's state SHALL be either `running` or `stopped`, enforced by the database. `stopped` means no workload of the deployment runs and only an explicit start runs it again. Pausing when idle is not a power state: it is a property of a running deployment, observed at runtime, and is recorded nowhere in the ledger.

#### Scenario: An unknown state is rejected

- **WHEN** a power row is written with a state other than `running` or `stopped`
- **THEN** the database rejects the write

### Requirement: The reason is one of a closed set

A power row's reason SHALL be either `manual` or `payment`, enforced by the database.
- `manual` covers an owner, administrator or operator action, in either direction.
- `payment` is reserved for stopping a deployment in payment arrears. No component produces it yet, but the schema SHALL accept it, so that the later phase adds a producer without a migration.

#### Scenario: An unknown reason is rejected

- **WHEN** a power row is written with a reason other than `manual` or `payment`
- **THEN** the database rejects the write

### Requirement: The reconciler records each power row's outcome once

A power row's outcome SHALL be written by the reconciler: when work began, when it ended, and any error. The start time SHALL be written only if not already set, so that a re-run after a worker died records when work first began. The end time and the error SHALL each be written once.

#### Scenario: A stop is applied

- **WHEN** the reconciler applies a stop successfully
- **THEN** the power row records when work began and when it ended, with no error

#### Scenario: A stop fails

- **WHEN** the reconcile applying a stop fails
- **THEN** the power row records when it ended and why

#### Scenario: A reclaimed reconcile

- **WHEN** a worker dies while applying a stop, and another worker reclaims the job and finishes it
- **THEN** the power row's start time is the time the first worker began

### Requirement: The deployment points at its desired and applied power

A deployment SHALL carry two nullable references into the power ledger: the power it desires and the power it is running. A null reference SHALL mean `running`, so that a deployment that was never stopped needs no power row. A power change SHALL move only the desired reference. Only a successful reconcile SHALL move the applied reference to the desired one.

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

### Requirement: Deployment reads expose desired and applied power from the database only

Every deployment read, single and listed, SHALL include a `power` object with:
- the desired state;
- the applied state;
- the desired row's reason, null when the desired state is `running`.

These fields SHALL come from the database alone, and a listing SHALL read them without a query per deployment. No field of a deployment read, single or listed, SHALL require a call to the Kubernetes API.

#### Scenario: A stopped deployment

- **WHEN** a deployment its owner stopped has been applied
- **THEN** its read reports desired `stopped`, applied `stopped` and reason `manual`

#### Scenario: A deployment that is stopping

- **WHEN** a stop has been requested but not yet applied
- **THEN** its read reports desired `stopped` and applied `running`

#### Scenario: A running deployment

- **WHEN** a deployment has never been stopped, or has been started again and the start applied
- **THEN** its read reports desired `running` and applied `running`, with no reason

#### Scenario: Listing many deployments

- **WHEN** an owner lists their deployments
- **THEN** every deployment's power is included, and the listing makes no call to the Kubernetes API

### Requirement: Power rows are removed with their deployment

Power rows SHALL belong to exactly one deployment and SHALL be removed when that deployment's row is removed.

#### Scenario: A deployment is purged

- **WHEN** a deployment row is deleted
- **THEN** its power rows are deleted with it
