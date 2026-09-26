# build-data-model Specification

## Purpose
Defines the build record: what a build is, the deployment it belongs to and through which
it is owned, the states it moves through, and the identifiers that tie it to its uploaded
artifact and its resulting container image.
## Requirements
### Requirement: A build belongs to a deployment

Every build SHALL belong to exactly one deployment, recorded when the build is created
and never changed. A build MUST NOT exist without one.

A build's owner SHALL be its deployment's owner. The build SHALL NOT record an owner of
its own, so that the two can never disagree.

A build SHALL outlive its deployment: deleting a deployment MUST NOT delete its builds,
and a build of a deleted deployment SHALL remain readable by that deployment's owner.

The system MUST NOT restrict how many builds a deployment may have, nor relate concurrent
builds to one another.

#### Scenario: A build records its deployment

- **WHEN** a build is created for a deployment
- **THEN** the build records that deployment, and its owner is that deployment's owner

#### Scenario: A build cannot be orphaned

- **WHEN** a build is written with no deployment
- **THEN** the write is rejected

#### Scenario: A deleted deployment keeps its builds

- **WHEN** a deployment is deleted
- **THEN** its builds remain, still attributed to it

#### Scenario: A deployment runs two builds at once

- **WHEN** a second build is created for a deployment while a first is still running
- **THEN** both builds are accepted and proceed independently, and neither supersedes the other

### Requirement: Build state machine

A build SHALL occupy exactly one of the states `queued`, `running`, `succeeded`,
`failed`, or `canceled`.

Permitted transitions are `queued → running`, `running → succeeded`, and
`running → failed`. `succeeded`, `failed`, and `canceled` are terminal. A failed build
MUST NOT be retried automatically; recovery is creating a new build.

The `canceled` state is reserved. No operation in this change transitions a build into it.

#### Scenario: Newly created build is queued

- **WHEN** a build is created
- **THEN** its status is `queued` and both its start and finish timestamps are unset

#### Scenario: Terminal states are final

- **WHEN** a build has reached `succeeded`, `failed`, or `canceled`
- **THEN** no subsequent operation changes its status

#### Scenario: Failure is not retried

- **WHEN** a build reaches `failed`
- **THEN** the system does not re-run it, and the build's Kubernetes Job is not recreated

### Requirement: Build exposes its resulting image only on success

A build SHALL expose an `image` value that is null until the build reaches `succeeded`,
at which point it MUST carry the reference `{user_id}@{digest}` — a container image
reference with the registry host removed.

The value MUST be a flat string, not a structured object. It is submitted verbatim by the
client as a product's `image` user value, so any reassembly by the client would be a place
for the two subsystems to diverge on format.

#### Scenario: Image is absent before success

- **WHEN** a build is in `queued`, `running`, or `failed`
- **THEN** its `image` value is null

#### Scenario: Image is present after success

- **WHEN** a build reaches `succeeded`
- **THEN** its `image` value is the string `{user_id}@sha256:<64 lowercase hex characters>`, where `{user_id}` is the build's owner

### Requirement: An artifact has at most one build in flight

The system SHALL permit at most one non-terminal build per artifact. Creating a build for
an artifact whose existing build is `queued` or `running`, for the same deployment, MUST
return that existing build rather than creating a second one. Creating a build for an
artifact whose builds have all reached a terminal status MUST create a new build.

Creating a build for an artifact whose in-flight build belongs to a different deployment
MUST be refused as a conflict. Returning that build would answer a request about one
deployment with a build of another.

This makes creation idempotent over the window in which retries actually occur — a client
retrying a request whose response was lost does so within seconds, while its original build
is certainly still non-terminal — without forbidding a rebuild of the same source.

Rebuilding matters because build failures are often transient: a package registry timeout,
a memory-exhausted node, a registry push that did not complete. Requiring the client to
re-upload an identical archive to retry would waste the upload for no benefit. How long a
rebuild remains possible is bounded naturally by the artifact's own expiry.

#### Scenario: Retry while a build is in flight returns the existing build

- **WHEN** a client creates a build for an artifact whose build for the same deployment is `queued` or `running`
- **THEN** the existing build is returned and no second build is created

#### Scenario: The same artifact for another deployment while in flight

- **WHEN** a client creates a build for an artifact whose in-flight build belongs to a different deployment
- **THEN** the request is refused as a conflict and no build is created

#### Scenario: Rebuild after failure is allowed

- **WHEN** a client creates a build for an artifact whose previous build reached `failed`
- **THEN** a new build is created for the same artifact

#### Scenario: Rebuild after success is allowed

- **WHEN** a client creates a build for an artifact whose previous build reached `succeeded`
- **THEN** a new build is created for the same artifact

### Requirement: Build records its Kubernetes Job and log

A build SHALL record the identifier of the Kubernetes Job created for it, null until that
Job exists, and SHALL accumulate the Job's output as text.

The Job identifier is what lets a worker other than the one that started a build
determine that build's true outcome.

#### Scenario: Job identifier is absent before the Job exists

- **WHEN** a build is `queued`, or is `running` but its Job has not yet been created
- **THEN** its Job identifier is null

#### Scenario: Job identifier is recorded once the Job exists

- **WHEN** a Kubernetes Job has been created for a build
- **THEN** the build records that Job's identifier

### Requirement: A build records its measured usage and whether it reached the ledger

A build SHALL record the resource usage its container reported — CPU time, integrated
working-set memory, peak memory, and the start and end of its run — all together or not at
all, so that a finished build that ran a Job and records none of them is identifiable as
one whose usage is estimated. It SHALL record when its usage was written to the usage
ledger, null until then.

These values SHALL be recorded when the worker observes the build finish, because the
container's report does not outlive the Job.

#### Scenario: Usage is stored when the build finishes

- **WHEN** the worker observes a build's Job finish with a usage report
- **THEN** the build records that usage

#### Scenario: A build that did not report records no usage

- **WHEN** the worker observes a build's Job finish without a usage report
- **THEN** the build records none of the usage values

#### Scenario: A build awaiting recording is identifiable

- **WHEN** a build has finished but its usage has not been written to the ledger
- **THEN** it records no ledger time, and that alone identifies it as pending
