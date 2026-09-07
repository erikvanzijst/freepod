## ADDED Requirements

### Requirement: Deployment create requires a claimed subdomain

Deployment create MUST NOT carry any subdomain field, for either REST
`POST /users/{user_id}/deployments` or the equivalent CLI command. Instead it MUST require
that the owning user already holds a subdomain (claimed via `POST /api/me/subdomain`). A
create for a user holding none MUST be rejected with a client error (**400**) and MUST NOT
create a deployment. The guard MUST be enforced server-side, so the claim-then-deploy flow
cannot be bypassed by a direct API or CLI client, exactly as the Terms of Service
precondition is.

The precondition is enforced at creation and not at authentication: an account with no
subdomain can sign in, read, and use every part of the platform that does not create a
deployment.

#### Scenario: Deploy after claiming succeeds

- **WHEN** a user holding a subdomain creates a deployment with an otherwise valid payload
- **THEN** the API creates the deployment, and its payload and response contain no subdomain
  field

#### Scenario: Deploy without a subdomain is rejected

- **WHEN** a user holding no subdomain attempts to create a deployment
- **THEN** the API responds **400** and no deployment is created

#### Scenario: CLI deploy without a subdomain is rejected

- **WHEN** an operator runs the CLI create-deployment command for a user holding none
- **THEN** the command fails without creating a deployment

#### Scenario: Updating an existing deployment does not check

- **WHEN** a deployment that already exists is updated
- **THEN** the subdomain precondition is not applied

#### Scenario: The two preconditions are reported separately

- **WHEN** a user has neither accepted the Terms nor claimed a subdomain
- **THEN** the rejection identifies which precondition failed rather than reporting one as
  the other
