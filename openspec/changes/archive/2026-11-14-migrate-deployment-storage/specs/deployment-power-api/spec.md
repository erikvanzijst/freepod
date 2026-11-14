# Spec Delta

## MODIFIED Requirements

### Requirement: Start lifts only stops the caller may lift

Start SHALL run a deployment whose desired power is `stopped` with reason `manual`. A deployment held for maintenance SHALL be refused with `409` and code `under_maintenance`, whatever its status, and SHALL record nothing. A deployment stopped for any other reason, such as `payment`, SHALL be refused with `409` and code `not_startable`, and SHALL record nothing.

#### Scenario: A deployment stopped for payment

- **WHEN** the owner starts a deployment stopped for payment
- **THEN** the request is refused with `409` and code `not_startable`

#### Scenario: A deployment held for maintenance

- **WHEN** the owner or an administrator starts a deployment held for maintenance
- **THEN** the request is refused with `409` and code `under_maintenance`, even if the deployment is `error`

## ADDED Requirements

### Requirement: An operator holds a deployment for maintenance

Operators SHALL be able to hold a deployment for maintenance, in-process and not over HTTP. Holding SHALL record a `stopped` row with reason `maintenance` and no actor, point the desired power at it and enqueue a reconcile, in one transaction. It SHALL be accepted only for a `ready` deployment, whatever its power (code `deployment_not_ready` otherwise), and refused while a reconcile is open. Holding a held deployment SHALL change nothing.

#### Scenario: Holding a running deployment

- **WHEN** an operator holds a ready, running deployment
- **THEN** a `stopped` row with reason `maintenance` and no actor is recorded, and a reconcile is queued

### Requirement: Releasing maintenance restores the power before it

Releasing SHALL record a row with the state and reason of the newest row outside maintenance that was applied without error, or `running` with reason `manual` when there is none. It SHALL have no actor and SHALL enqueue a reconcile. It SHALL be accepted for a `ready` or `error` deployment. Releasing a deployment that is not held SHALL change nothing.

#### Scenario: Releasing restores the owner's own stop

- **WHEN** a deployment its owner had stopped is held and then released
- **THEN** the release records `stopped` with reason `manual`, and the deployment stays stopped

#### Scenario: Releasing restores a payment stop

- **WHEN** a deployment stopped for payment is held and then released
- **THEN** it is stopped for payment again

#### Scenario: A deployment that never changed power

- **WHEN** a deployment with no earlier power row is held and released
- **THEN** the release records `running` with reason `manual`

#### Scenario: Failed and superseded rows are skipped

- **WHEN** the newest rows before the hold are a start that failed and a start that was never applied
- **THEN** releasing restores the stop applied before them

#### Scenario: Releasing a failed deployment

- **WHEN** a held deployment's last reconcile failed
- **THEN** releasing it is accepted

### Requirement: A deployment held for maintenance accepts no release

Updating a deployment held for maintenance SHALL be refused with `409` and code `under_maintenance`, and SHALL create no release, change no status and enqueue nothing. The refusal SHALL hold even when the hold lands between the request's checks and its write. Stop SHALL change nothing, as for any stopped deployment. Delete SHALL be accepted.

#### Scenario: An update during maintenance

- **WHEN** the owner, an administrator or the upgrader updates a held deployment
- **THEN** the request is refused with `409` and code `under_maintenance`, and the deployment's desired release is unchanged

#### Scenario: Updating after maintenance

- **WHEN** the deployment has been released from maintenance and the reconcile has finished
- **THEN** an update is accepted again
