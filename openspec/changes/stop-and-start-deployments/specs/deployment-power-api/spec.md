## Purpose

Stopping and starting a deployment on request: the REST endpoints and their `caelus` equivalents, who may call them, when they are accepted, and what they answer.

## ADDED Requirements

### Requirement: A deployment can be stopped

`POST /api/users/{user_id}/deployments/{deployment_id}/stop` SHALL stop the deployment: in one transaction it SHALL record a `stopped` power row with reason `manual`, point the deployment's desired power at it, and enqueue a reconcile. It SHALL answer with the deployment read.

#### Scenario: Stopping a running deployment

- **WHEN** the owner stops a running, `ready` deployment
- **THEN** the response is the deployment, with desired power `stopped` and applied power `running`
- **AND** a reconcile is queued for it

### Requirement: A deployment can be started

`POST /api/users/{user_id}/deployments/{deployment_id}/start` SHALL start a stopped deployment: in one transaction it SHALL record a `running` power row with reason `manual`, point the desired power at it, and enqueue a reconcile. It SHALL answer with the deployment read.

#### Scenario: Starting a stopped deployment

- **WHEN** the owner starts a stopped, `ready` deployment
- **THEN** the response is the deployment, with desired power `running` and applied power `stopped`
- **AND** a reconcile is queued for it

### Requirement: Power changes require a ready deployment

Stop and start SHALL be accepted only for a deployment whose status is `ready`. Any other status SHALL be refused with `409` and code `deployment_not_ready`, and SHALL record nothing. A failed deployment's state is uncertain, and re-applying it with a different power would make the outcome unpredictable.

#### Scenario: A failed deployment cannot be stopped

- **WHEN** the owner stops a deployment whose status is `error`
- **THEN** the request is refused with `409` and code `deployment_not_ready`
- **AND** no power row is recorded and no reconcile is queued

#### Scenario: A deployment still provisioning cannot be stopped

- **WHEN** the owner stops a deployment whose status is `provisioning`
- **THEN** the request is refused with `409` and code `deployment_not_ready`

### Requirement: A power change refused by an open reconcile records nothing

When a reconcile for the deployment is already queued or running, stop and start SHALL be refused with `409`, as every other deployment write is, and the transaction SHALL be rolled back so that no power row remains.

#### Scenario: Stopping while a reconcile is running

- **WHEN** a deployment's reconcile is running and the owner sends stop or start
- **THEN** the request is refused with `409`
- **AND** no power row is recorded

### Requirement: Power requests are idempotent

A stop for a deployment whose desired power is already `stopped`, or a start for one whose desired power is already `running`, SHALL record nothing, enqueue nothing and answer with the deployment read, whether or not the earlier change has been applied yet.

#### Scenario: Stopping twice

- **WHEN** the owner stops a deployment that is already stopped or stopping
- **THEN** the response is the deployment as it stands
- **AND** no power row is recorded and no reconcile is queued

#### Scenario: Starting a running deployment

- **WHEN** the owner starts a deployment whose desired power is `running`
- **THEN** the response is the deployment as it stands, and nothing is recorded

### Requirement: Start lifts only stops the caller may lift

Start SHALL run a deployment whose desired power is `stopped` with reason `manual`. A deployment stopped for any other reason, such as `payment`, SHALL be refused with `409` and code `not_startable`, and SHALL record nothing.

#### Scenario: A deployment stopped for payment

- **WHEN** the owner starts a deployment stopped for payment
- **THEN** the request is refused with `409` and code `not_startable`

### Requirement: Power endpoints are owner-authorized

Stop and start SHALL be authorized as every other deployment write: the deployment's owner, or an administrator, MAY call them; anyone else SHALL receive `403`. A deployment that does not exist under the given user SHALL answer `404`. The power row SHALL record the caller as its actor.

#### Scenario: An administrator stops someone else's deployment

- **WHEN** an administrator stops another user's deployment
- **THEN** the deployment is stopped and the power row records the administrator as actor

#### Scenario: Another user is refused

- **WHEN** a non-administrator stops a deployment they do not own
- **THEN** the request is refused with `403`

### Requirement: The operator CLI has stop and start

`caelus` SHALL offer `stop-deployment` and `start-deployment`, taking the owner's user id and the deployment id, with the same preconditions, idempotence and errors as the REST endpoints. A power row recorded through `caelus` SHALL have no actor, marking it as a platform action.

#### Scenario: An operator stops a deployment

- **WHEN** an operator runs `caelus stop-deployment` for a `ready` deployment
- **THEN** the deployment is stopped exactly as through the API
- **AND** the power row records no actor

#### Scenario: The same refusal through either surface

- **WHEN** an operator runs `caelus start-deployment` for a deployment whose status is `error`
- **THEN** the command fails with the same `deployment_not_ready` refusal the API gives
