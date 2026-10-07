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

A subject MAY be a tenant database. A database subject's deployment is the one the
platform's record of that database names, rather than one resolved from the namespace it
was observed in, since every tenant database is served from one shared cluster. Its
reference is the database's name, which is unique to its deployment.

A subject MAY be an object storage bucket. A bucket subject's deployment is the one whose
identifier the bucket's name carries, confirmed against the platform's deployment
records, since every bucket is served from one shared object store. Its reference is the
bucket's name, `dep-<deployment id>`, which is unique to its deployment.

Subject records MAY be updated as attribution improves; samples MUST NOT.

#### Scenario: Usage is attributed to the owning user

- **WHEN** usage is summed for a user over a period
- **THEN** every subject attributed to one of that user's deployments is included,
  whether a container in the deployment's namespace, one of its builds, its database or
  its bucket

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

#### Scenario: A database is attributed to its own deployment

- **WHEN** a tenant database's usage is recorded
- **THEN** its subject is of kind `database` and attributed to the deployment the
  platform's record of that database names, not to the shared cluster's namespace

#### Scenario: A bucket is attributed to its own deployment

- **WHEN** a bucket's usage is recorded
- **THEN** its subject is of kind `bucket`, its reference is the bucket's name, and it is
  attributed to the deployment that name carries, not to the object store's namespace

### Requirement: Consumption and allowance are recorded side by side

For each axis where an allowance exists, the system SHALL record both what was consumed
and what was allowed, as separate catalogued quantities against the same subject and
window, with one exception: object storage.

Object storage SHALL record consumption only. Its allowance, the plan's storage quota
enforced by the object store, is constant per plan and derivable from the plan when
needed. Recording it every window would double the rows of the axis with the most
subjects.

#### Scenario: Requests and usage are both available

- **WHEN** a container's CPU and memory are recorded for a window
- **THEN** both the consumed quantities and the requested and limited allowances are
  recorded, and either can be summed independently

#### Scenario: Object storage records consumption alone

- **WHEN** a bucket's size is recorded for a window
- **THEN** one quantity is recorded for that subject and window, and no allowance
