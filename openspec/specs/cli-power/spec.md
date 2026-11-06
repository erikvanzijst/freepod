# cli-power Specification

## Purpose

Stopping and starting a project's deployment from the command line with `freepod stop` and `freepod start`: which deployment they address, how they follow the change to completion, and how other commands report a stopped deployment.

## Requirements

### Requirement: Power commands address only the deployment the project records

`freepod stop` and `freepod start` SHALL act on the deployment recorded in the project file and SHALL NOT accept a deployment named by the caller. With no project file, or one that records no deployment, they SHALL refuse with a usage error. A deployment recorded on another environment SHALL be refused, naming that environment.

#### Scenario: Outside a project

- **WHEN** `freepod stop` runs where no project file exists
- **THEN** the client refuses with a usage error and makes no request

#### Scenario: A deployment on another environment

- **WHEN** the project records its deployment on another environment than the one targeted
- **THEN** the client refuses and names the environment the deployment lives on

### Requirement: Stopping asks for no confirmation

`freepod stop` SHALL request the stop without a confirmation prompt, because stopping is undone by `freepod start` and loses no data. It SHALL tell the user that visitors see a "stopped" page until the deployment is started again.

#### Scenario: Stopping a running deployment

- **WHEN** `freepod stop` runs for a running deployment
- **THEN** the stop is requested without a prompt
- **AND** the user is told how to start it again

### Requirement: The power change is followed to completion by default

After the platform accepts the change, the client SHALL wait until the deployment's applied power equals the requested power, then report success. The caller MAY waive the wait, in which case the client SHALL say the change continues in the background. If the deployment's status becomes `error` instead, the client SHALL report the failure with the reason the platform recorded and exit with a failure status.

#### Scenario: Waiting for a stop

- **WHEN** `freepod stop` runs and the reconcile succeeds
- **THEN** the client reports the deployment stopped only once its applied power is `stopped`

#### Scenario: Not waiting

- **WHEN** `freepod stop` runs with the wait waived
- **THEN** the client returns once the platform has accepted the change and says it continues

#### Scenario: A failed change

- **WHEN** the deployment's status becomes `error` while the client waits
- **THEN** the client reports the platform's recorded reason and exits with a failure status

### Requirement: Repeating a power command is not an error

When the deployment already has the requested power, desired or applied, the client SHALL say so and exit successfully. When the change is still in progress, it SHALL follow it as if it had requested it.

#### Scenario: Starting a running deployment

- **WHEN** `freepod start` runs for a deployment that is running
- **THEN** the client reports that it is already running and exits successfully

### Requirement: Refusals are explained in the user's terms

The client SHALL turn the platform's refusals into actionable messages. A deployment that is not `ready` SHALL be reported with its status and how to fix it. A deployment with a rollout in progress SHALL be reported as busy, with the advice to retry. A stop the user cannot lift SHALL be reported as such, naming its reason.

#### Scenario: A failed deployment

- **WHEN** the platform refuses with code `deployment_not_ready` for a deployment in `error`
- **THEN** the client says the deployment is failed and that a successful `freepod deploy` is needed first

#### Scenario: A deployment stopped for payment

- **WHEN** the platform refuses start with code `not_startable`
- **THEN** the client says the deployment is stopped for payment and cannot be started from the CLI

### Requirement: Deploying to a stopped deployment says it stays stopped

When `freepod deploy` completes a rollout to a deployment whose desired power is `stopped`, the client SHALL say that the deployment remains stopped and that `freepod start` runs it. It SHALL NOT start the deployment itself.

#### Scenario: Deploying while stopped

- **WHEN** `freepod deploy` rolls out to a stopped deployment
- **THEN** the rollout completes, the deployment stays stopped, and the client points at `freepod start`
