## Purpose

How a Vaultwarden deployment makes sure its owner can sign in. A fresh instance has no users and signups are closed, so the owner is invited through the admin API. The invite runs whenever the app's container starts, not as a Helm hook.

## ADDED Requirements

### Requirement: The owner is invited whenever the app starts

Every time the Vaultwarden container starts, the deployment SHALL invite the owner's email address through Vaultwarden's admin API, once Vaultwarden answers its health endpoint. Vaultwarden then emails the owner a link to choose a master password. This SHALL happen without a Helm hook, and without any workload other than the app's own container.

#### Scenario: A fresh deployment

- **WHEN** a new Vaultwarden deployment starts for the first time
- **THEN** the owner receives an invitation at their account's email address

#### Scenario: No hook in the chart

- **WHEN** the Vaultwarden chart is rendered
- **THEN** it renders no Helm hook and no Job

### Requirement: Repeating the invite is harmless

An invite for an owner who is already invited or registered SHALL count as success, so that restarts, rollouts and starts after a stop do not fail.

#### Scenario: A restart

- **WHEN** the container of an existing Vaultwarden deployment restarts
- **THEN** the invite is answered as already done, and the container starts normally

#### Scenario: Starting a stopped deployment

- **WHEN** a stopped Vaultwarden deployment is started
- **THEN** the start succeeds and the owner receives no new invitation

### Requirement: An account created without its email still counts

When the invite fails but the owner's account exists, because the account was created and only the notification email failed, the deployment SHALL treat it as success. It SHALL log that the owner can complete registration with that address.

#### Scenario: The mail server is unreachable

- **WHEN** the invite creates the owner's account but the invitation email cannot be sent
- **THEN** the container starts normally and its log says how the owner can finish registering

### Requirement: A failed invite keeps the app from becoming ready

When Vaultwarden does not answer its health endpoint within the configured time (default 120 seconds), or the invite fails and no account exists, the container SHALL fail to start, and the platform SHALL retry by restarting it. During an install or upgrade, a failure that persists SHALL fail the rollout and roll it back, as a failed first-run step did before.

#### Scenario: A wrong admin token

- **WHEN** the admin API refuses the deployment's admin token
- **THEN** the container restarts, the pod does not become ready, and the rollout rolls back

### Requirement: The invite's outcome is in the app's log

The invite's outcome SHALL appear in the container's log, whether it invited the owner, found the owner already invited or registered, completed with an email failure, or failed.

#### Scenario: Reading the log

- **WHEN** an operator reads the Vaultwarden container's log after it starts
- **THEN** a line states the invite's outcome
