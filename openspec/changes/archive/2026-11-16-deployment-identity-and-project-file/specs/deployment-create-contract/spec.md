# Spec Delta

## MODIFIED Requirements

### Requirement: Deployment reads return name and namespace
The system MUST include `name` and `namespace` in deployment read responses. `name` is the owner-chosen name of deployment-identity, not the generated release name. The field `deployment_uid` MUST NOT appear in API responses.

#### Scenario: Read deployment returns name and namespace fields
- **WHEN** a client retrieves a deployment using the read endpoint
- **THEN** the response includes the `name` and `namespace` fields
- **AND** the response does NOT include a `deployment_uid` field

## ADDED Requirements

### Requirement: Create accepts the deployment's identity and managed fields

The create contract SHALL accept optional `name`, `description`, `icon` and
`managed_fields`, as the update does, validated as deployment-identity and
deployment-project-file require. A name in use SHALL refuse the create with `409` and
code `name_in_use` before anything is provisioned or charged, including before a
checkout is opened for a paid plan.

#### Scenario: Creating with a name

- **WHEN** a deployment is created with `name: "Arkanoid"`
- **THEN** the created deployment is named `Arkanoid`

#### Scenario: A name already in use

- **WHEN** the owner already has a live deployment named `Arkanoid` and creates another with that name
- **THEN** the request is refused with `409` and code `name_in_use`
- **AND** no deployment, subscription or checkout is created

#### Scenario: Creating with managed fields

- **WHEN** a deployment is created with `auth` in its values and `managed_fields` of `["auth"]`
- **THEN** the created deployment's managed fields are `auth`
