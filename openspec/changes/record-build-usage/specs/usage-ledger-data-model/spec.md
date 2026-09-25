## MODIFIED Requirements

### Requirement: Subjects carry attribution, and it survives deletion

The system SHALL record each quantity against a subject: the thing that consumed it.
A subject MUST declare its kind and a reference that is stable for that subject's
lifetime, and MUST be unique on that pair.

A subject MUST carry the namespace it was observed in and, where one resolves, the
deployment that owns it. Attribution MUST remain resolvable after the deployment is
deleted. A subject that resolves to no deployment — a platform namespace — MUST still
be recorded, with no deployment attributed.

A subject MAY be a build rather than a container. A build subject's deployment is the one
the build belongs to, taken from the build's own record rather than from the namespace it
ran in, since builds run in a namespace shared by every deployment.

Subject records MAY be updated as attribution improves; samples MUST NOT.

#### Scenario: Usage is attributed to the owning user

- **WHEN** usage is summed for a user over a period
- **THEN** every subject attributed to one of that user's deployments is included,
  whether a container in the deployment's namespace or one of its builds

#### Scenario: A deleted deployment keeps its history

- **WHEN** a deployment is deleted and its usage is queried for a past period
- **THEN** the samples remain attributed to that deployment and its owner

#### Scenario: Platform overhead is recorded

- **WHEN** a namespace belongs to the platform rather than a tenant
- **THEN** its subjects are recorded with no deployment attributed, and its usage is
  queryable as unattributed overhead

#### Scenario: A re-created volume is a distinct subject

- **WHEN** a persistent volume is destroyed and a new one created for the same
  deployment
- **THEN** the new volume is recorded as a new subject, and both remain attributed to
  the same deployment through their namespace

#### Scenario: A build is attributed to its own deployment

- **WHEN** a build's usage is recorded
- **THEN** its subject is of kind `build` and attributed to the deployment the build
  belongs to, not to the shared namespace it ran in
