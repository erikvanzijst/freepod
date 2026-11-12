# Spec Delta

## MODIFIED Requirements

### Requirement: The status label reflects power

A `ready` deployment's status label SHALL be:
- **Maintenance** while its desired power is `stopped` with reason `maintenance`, whatever its applied power;
- otherwise **Stopped** when its desired and applied power are both `stopped`;
- **Stopping** while its desired power is `stopped` and its applied power is `running`;
- **Starting** while its desired power is `running` and its applied power is `stopped`.

Maintenance, Stopping and Starting SHALL show progress. Maintenance SHALL say that the app returns to how it was afterwards. Statuses other than `ready` SHALL keep their existing labels.

#### Scenario: A stopped app

- **WHEN** a deployment is `ready` with desired and applied power `stopped`
- **THEN** its row is labeled Stopped, without progress

#### Scenario: An app being stopped

- **WHEN** a deployment is `ready` with desired power `stopped` and applied power `running`
- **THEN** its row is labeled Stopping, with progress

#### Scenario: An app being started

- **WHEN** a deployment is `ready` with desired power `running` and applied power `stopped`
- **THEN** its row is labeled Starting, with progress

#### Scenario: An app under maintenance

- **WHEN** a deployment is `ready` with desired power `stopped` for `maintenance`
- **THEN** its row is labeled Maintenance, with progress

## ADDED Requirements

### Requirement: An app under maintenance offers no changes

A deployment whose desired power is `stopped` for `maintenance` SHALL offer neither Start, Stop nor Edit, whatever its status. Remove SHALL stay available. A start refused with code `under_maintenance` SHALL be explained as maintenance.

#### Scenario: The row of an app under maintenance

- **WHEN** the owner views an app held for maintenance
- **THEN** the row offers Remove only

#### Scenario: A failed app under maintenance

- **WHEN** an app held for maintenance has status `error`
- **THEN** its row offers no Edit
