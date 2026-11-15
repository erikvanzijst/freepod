# Spec Delta

## MODIFIED Requirements

### Requirement: A release is created by the request that asks for a rollout

Creating a deployment SHALL create exactly one release. Updating a deployment SHALL
create exactly one release when the update releases, as edit-deployment-backend's "An
update releases only when the running app would change" defines, and none otherwise. A
release SHALL be created in the **same transaction** as the deployment write, and SHALL
be recorded as the deployment's desired release.

A release SHALL carry a `uuid4` primary key, generated before anything exists in the cluster to
carry it. That identifier SHALL be the value stamped onto the release's pods, and SHALL be
unguessable, globally unique, and never reused.

A release SHALL belong to exactly one deployment. It SHALL NOT be shared between deployments,
reassigned, or created by the reconciler.

Where the deployment write is rejected — a failed guard, a validation error — the release SHALL NOT
be created either.

A deployment SHALL always name a desired release. There SHALL be no deployment without one, at any
point after its creating transaction commits, including deployments that predate this capability.

#### Scenario: A deployment is created

- **WHEN** a deployment is created
- **THEN** a release exists for it, and the deployment names it as its desired release

#### Scenario: A deployment is updated

- **WHEN** a deployment's chart values are updated
- **THEN** a new release exists, and the deployment names the new one as its desired release

#### Scenario: A rejected update

- **WHEN** an update is rejected because the deployment is not in an updatable state
- **THEN** no release is created

#### Scenario: A deployment predating the ledger

- **WHEN** a deployment that existed before releases were recorded is read
- **THEN** it names a desired release
- **AND** it names an applied release only if it had previously been applied

#### Scenario: Two byte-identical redeploys

- **WHEN** a `ready` deployment receives the same update twice, naming no build and carrying no vars
- **THEN** the second update creates no release

#### Scenario: An identity-only update

- **WHEN** an update changes only the deployment's description
- **THEN** no release is created and the desired release is unchanged
