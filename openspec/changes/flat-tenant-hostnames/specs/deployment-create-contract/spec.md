# Spec Delta

## ADDED Requirements

### Requirement: Deployment create requires a claimed handle

Deployment create MUST NOT carry any handle field, for either REST
`POST /users/{user_id}/deployments` or the equivalent CLI command, and MUST require that the
owning user already holds a handle. A create for a user holding none MUST be refused with
**400** and the stable code `handle_required`, server-side, and MUST NOT create a
deployment. Updates do not apply this precondition.

#### Scenario: Deploy after claiming succeeds

- **WHEN** a user holding a handle creates a deployment with an otherwise valid payload
- **THEN** the API creates the deployment, and its payload and response contain no handle
  field

#### Scenario: Deploy without a handle is rejected

- **WHEN** a user holding no handle attempts to create a deployment
- **THEN** the API responds **400** with code `handle_required` and no deployment is created

#### Scenario: CLI deploy without a handle is rejected

- **WHEN** an operator runs the CLI create-deployment command for a user holding none
- **THEN** the command fails without creating a deployment

#### Scenario: Updating an existing deployment does not check

- **WHEN** a deployment that already exists is updated
- **THEN** the handle precondition is not applied

#### Scenario: The two preconditions are reported separately

- **WHEN** a user has neither accepted the Terms nor claimed a handle
- **THEN** the rejection identifies which precondition failed by its own error code rather
  than reporting one as the other

### Requirement: A tenant hostname carries its owner's handle

On create and on update, a hostname under the tenant domain MUST end in the owning user's
handle, as `hostname-validation` defines. A create or update naming another account's handle
MUST be rejected and MUST NOT be persisted. Hostnames outside the tenant domain are
unaffected.

#### Scenario: A deployment under the owner's own handle is accepted

- **WHEN** a user holding `alice` creates a deployment with hostname
  `photos-alice.freepod.app`
- **THEN** the create proceeds

#### Scenario: A deployment under another account's handle is refused

- **WHEN** a user holding `bob` creates a deployment with hostname `photos-alice.freepod.app`
- **THEN** the create is rejected and no deployment is created

#### Scenario: An update cannot move a deployment under another handle

- **WHEN** a user holding `bob` updates a deployment's hostname to
  `photos-alice.freepod.app`
- **THEN** the update is rejected

#### Scenario: A custom domain is unaffected

- **WHEN** a user creates a deployment with hostname `photos.example.com`
- **THEN** the ownership rule does not apply

## MODIFIED Requirements

### Requirement: Create and update services derive hostname from template schema and user values
During create-deployment and update-deployment, the service MUST derive `DeploymentORM.hostname` from `user_values_json` using the schema from `desired_template`. The schema field is identified by `title` matching `hostname` (case-insensitive). A bare application label MUST be completed beneath the owner's handle (see `hostname-validation`), and the completed, lowercased FQDN MUST be written back into `user_values_json` at that field and persisted as `DeploymentORM.hostname`, so the chart always receives a fully qualified name.

Additionally, the create-deployment service MUST generate and persist both `DeploymentORM.name` (Helm release name) and `DeploymentORM.namespace` (Kubernetes namespace) at creation time, using the naming functions defined in the `deployment-naming` and `deployment-namespace` capabilities.

#### Scenario: Template schema contains a hostname-titled field
- **WHEN** the desired template schema contains one or more fields anywhere in the schema document whose `title` matches `hostname` case-insensitively
- **THEN** the service selects the first matching field and persists `DeploymentORM.hostname` from the corresponding `user_values_json` value

#### Scenario: A bare label is completed and written back
- **WHEN** a user holding `alice` creates a deployment whose hostname field is `photos` and the tenant domain is `freepod.app`
- **THEN** the deployment's `hostname` is `photos-alice.freepod.app`, and its stored user values carry `photos-alice.freepod.app` at that field

#### Scenario: Template schema has no hostname-titled field
- **WHEN** the desired template schema contains no field whose `title` equals `hostname`
- **THEN** the service persists `DeploymentORM.hostname` as `null`

#### Scenario: Update re-derives hostname
- **WHEN** a client updates a deployment with new `user_values_json`
- **THEN** the service re-derives and persists `DeploymentORM.hostname` using the same recursive first-match rule

#### Scenario: Deployment creation generates name and namespace
- **WHEN** a new deployment is created
- **THEN** the service generates `name` using `generate_deployment_name(product_name)` and `namespace` using `generate_deployment_namespace(user_email)`
- **AND** both values are persisted to the deployment record before flushing

## REMOVED Requirements

### Requirement: Deployment create requires a claimed subdomain
**Reason**: The account subdomain is now the account handle.
**Migration**: See *Deployment create requires a claimed handle*. The error code is now
`handle_required`.

### Requirement: A deployment hostname sits beneath its own owner's subdomain
**Reason**: Tenant hostnames are flat, and ownership is expressed by the handle at the end of
the label.
**Migration**: See *A tenant hostname carries its owner's handle*.
