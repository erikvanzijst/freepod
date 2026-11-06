## Purpose

How the dashboard shows a deployment's power state and lets its owner stop and start it.

## ADDED Requirements

### Requirement: The status label reflects power

A `ready` deployment's status label SHALL be:
- **Stopped** when its desired and applied power are both `stopped`;
- **Stopping** while its desired power is `stopped` and its applied power is `running`;
- **Starting** while its desired power is `running` and its applied power is `stopped`.

Stopping and Starting SHALL show progress. Statuses other than `ready` SHALL keep their existing labels.

#### Scenario: A stopped app

- **WHEN** a deployment is `ready` with desired and applied power `stopped`
- **THEN** its row is labeled Stopped, without progress

#### Scenario: An app being stopped

- **WHEN** a deployment is `ready` with desired power `stopped` and applied power `running`
- **THEN** its row is labeled Stopping, with progress

#### Scenario: An app being started

- **WHEN** a deployment is `ready` with desired power `running` and applied power `stopped`
- **THEN** its row is labeled Starting, with progress

### Requirement: A running app can be stopped from its row

A `ready` deployment whose desired power is `running` SHALL offer a **Stop** action. Stop SHALL ask for confirmation, explaining that the app stops running, that its data is kept, and that visitors see a "stopped" page until it is started again. Confirming SHALL request the stop.

#### Scenario: Stopping an app

- **WHEN** the owner chooses Stop on a running app and confirms
- **THEN** the stop is requested and the row shows Stopping

#### Scenario: Declining

- **WHEN** the owner chooses Stop and cancels the confirmation
- **THEN** nothing is requested

### Requirement: A stopped app can be started from its row

A `ready` deployment whose desired power is `stopped` SHALL offer a **Start** action in place of Stop, unless it was stopped for a reason the owner cannot lift. Start SHALL request the start without confirmation.

#### Scenario: Starting an app

- **WHEN** the owner chooses Start on a stopped app
- **THEN** the start is requested and the row shows Starting

#### Scenario: No action while failed

- **WHEN** a deployment's status is not `ready`
- **THEN** its row offers neither Stop nor Start

### Requirement: The dashboard follows power changes

While any listed deployment's desired and applied power differ, the dashboard SHALL refresh the listing on the same cadence it uses for other transitional states, and SHALL stop once they agree.

#### Scenario: Stopping completes

- **WHEN** the owner stops an app and the reconcile completes
- **THEN** the row changes from Stopping to Stopped without a manual reload

### Requirement: A refused power change is shown

When the platform refuses a Stop or Start, the dashboard SHALL show the refusal in the row and leave its state as the platform reports it.

#### Scenario: A rollout is in progress

- **WHEN** the platform refuses Stop with `409` because a reconcile is open
- **THEN** the row shows that the app is busy and to try again shortly
