# Spec Delta

## MODIFIED Requirements

### Requirement: Refusals are explained in the user's terms

The client SHALL turn the platform's refusals into actionable messages. A deployment that is not `ready` SHALL be reported with its status and how to fix it. A deployment with a rollout in progress SHALL be reported as busy, with the advice to retry. A stop the user cannot lift SHALL be reported as such, naming its reason.

#### Scenario: A failed deployment

- **WHEN** the platform refuses with code `deployment_not_ready` for a deployment in `error`
- **THEN** the client says the deployment is failed and that a successful `freepod deploy` is needed first

#### Scenario: A deployment stopped for payment

- **WHEN** the platform refuses start with code `not_startable`
- **THEN** the client says the deployment is stopped for payment and cannot be started from the CLI

#### Scenario: A deployment held for maintenance

- **WHEN** the platform refuses start with code `under_maintenance`
- **THEN** the client says the deployment is stopped for platform maintenance, returns to how it was once that ends, and can be retried later
