# deployment-release-ledger Specification

## Purpose

What a *release* is — the record of one rollout of a deployment, created by the request that asks
for it and completed by the reconciler that applies it — and how status and liveness are answered
without any field being revised after it is written.

## Requirements
### Requirement: A release is created by the request that asks for a rollout

Creating or updating a deployment SHALL create exactly one release, in the **same transaction** as
the deployment write, and SHALL record it as the deployment's desired release.

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

- **WHEN** a deployment is updated
- **THEN** a new release exists, and the deployment names the new one as its desired release

#### Scenario: A rejected update

- **WHEN** an update is rejected because the deployment is not in an updatable state
- **THEN** no release is created

#### Scenario: A deployment predating the ledger

- **WHEN** a deployment that existed before releases were recorded is read
- **THEN** it names a desired release
- **AND** it names an applied release only if it had previously been applied

#### Scenario: Two byte-identical redeploys

- **WHEN** a deployment is updated twice with the same values, template and build
- **THEN** two distinct releases exist, distinguished by identity rather than by content

### Requirement: A release records the intent that produced it

A release SHALL record the template it is to be applied from, a snapshot of the user values it was
requested with, and the build it deploys where the product has one.

The values snapshot SHALL be the **user** values, not the merged values. System overrides are
computed by the reconciler and are largely per-apply platform detail; the user values are the
intent, and are what a comparison between releases or a later replay would need.

A release SHALL carry a nullable `build_id` foreign key. A null `build_id` SHALL NOT be treated as
an error or as an incomplete record: builds exist only for products that deploy tenant-supplied
code.

#### Scenario: A release of tenant-supplied code

- **WHEN** a deployment is updated naming a build
- **THEN** the release records that build
- **AND** the chain from artifact through build to the release's pods is traceable without
  inspecting the cluster

#### Scenario: A release of a curated product

- **WHEN** a curated product is deployed, with no build involved
- **THEN** the release's `build_id` is null and the release is otherwise complete

### Requirement: The build reference belongs to the release alone

The build reference SHALL be accepted as a field on the deployment create and update requests and
stored on the release. It SHALL NOT be stored on the deployment, which has no build-shaped state
because builds exist only for some products while deployments are general.

A request field that the deployment does not store is an established shape on these endpoints and
SHALL NOT require an envelope, a nested object or a query parameter to carry it.

The build reference SHALL NOT be passed to Helm. Chart values carry what a chart renders; a build
reference is never rendered by any chart.

#### Scenario: A build is named on a request

- **WHEN** a request names a build
- **THEN** the release records it
- **AND** the deployment stores no reference to it

#### Scenario: Helm values

- **WHEN** a release is applied
- **THEN** the values passed to Helm contain no build reference

### Requirement: A named build must belong to the deployment

A build reference is optional on every write. Where one is named, it SHALL exist and
SHALL belong to the deployment being created or updated; a request naming any other
build SHALL be rejected. On creation, where no deployment exists yet, no build can
belong to it, so a creation request naming a build SHALL be rejected.

Validation SHALL occur at the write, where the caller can still be told, and SHALL NOT be
deferred to the reconciler.

Belonging is the **only** condition. The platform SHALL NOT require agreement between a
named build and any value in the deployment's user values, and SHALL NOT require a build
to be named because some value is present.

`image` is a value of one product's chart, not a platform-wide concept: most products
build nothing, charts choose their own value names, and a single build or release may
come to carry more than one image. A rule tying the ledger to a particular chart's value
key would make the release record an artifact of `custom`'s schema. An image reference
could not identify a build on its own in any case: it is content-addressed, so more than
one build can produce the same reference.

#### Scenario: A build of another deployment

- **WHEN** an update names a build belonging to a different deployment, even one the caller owns
- **THEN** the request is rejected, and no provenance from it is recorded

#### Scenario: A build that does not exist

- **WHEN** a request names a build that does not exist
- **THEN** the request is rejected, indistinguishably from one belonging to another deployment

#### Scenario: A build named on creation

- **WHEN** a deployment creation request names a build
- **THEN** the request is rejected and no deployment is created

#### Scenario: An image reused without its build

- **WHEN** an update submits an image produced by another deployment's build, naming no build
- **THEN** the request is accepted and the release records no build

#### Scenario: No build is named

- **WHEN** a deployment is written with no build named, whatever its user values carry
- **THEN** the request is accepted and the release records no build

### Requirement: Releases are numbered per deployment

A release SHALL carry a monotonically increasing integer, unique within its deployment and starting
at 1, assigned when the record is created and never revised.

The number SHALL be the identifier presented to users and accepted from them, because a small
integer is what a person can read, repeat and type. The `uuid4` SHALL remain the value stamped onto
pods, because that value must be unguessable.

The number SHALL be the ordering key for a deployment's releases, in preference to timestamps, so
that ordering does not depend on clock resolution.

#### Scenario: Numbering is per deployment

- **WHEN** a deployment's third rollout is requested
- **THEN** its release is numbered 3, regardless of how many releases other deployments have

#### Scenario: A failed rollout consumes a number

- **WHEN** a rollout fails
- **THEN** its number is not reassigned to the next release

### Requirement: No release column is revised after it is written

A release SHALL NOT contain any field that is rewritten once set. Identity and intent SHALL be
written by the request; the outcome — when work began, when it ended, any error, and the applied
Helm revision — SHALL be written by the reconciler.

The field recording when work began SHALL be written only if it is not already set, so that a
reconcile re-run after a worker died mid-apply records when work *first* began. How many attempts
occurred SHALL be read from the reconcile job, not inferred from the release.

The record SHALL NOT contain a status field. A stored status would require a transition to be
written when something else changes — notably when an atomic rollback restores an earlier release —
by code that is not observing it.

#### Scenario: A rollout succeeds

- **WHEN** a rollout completes successfully
- **THEN** the release records when it ended, with no error

#### Scenario: A rollout fails

- **WHEN** a rollout fails and is rolled back
- **THEN** the release records when it ended and why
- **AND** the release is retained, because a failed rollout is the one a user needs to inspect

#### Scenario: A release is superseded

- **WHEN** a later release for the same deployment succeeds
- **THEN** no column on the earlier release is modified

#### Scenario: An atomic rollback restores an earlier release

- **WHEN** a rollout fails and Helm rolls back to the previously applied release
- **THEN** no column on that earlier release is modified

#### Scenario: A reconcile is re-run after a worker died mid-apply

- **WHEN** a reconcile is re-run for a release whose work had already begun
- **THEN** the recorded start time is unchanged
- **AND** the outcome is recorded on the same release

### Requirement: Release status is derived, never stored

A release's status SHALL be derived from whether work has begun, whether it has ended, and whether
it ended with an error:

- work not begun — queued
- begun, not ended — in flight, or abandoned once it has been so for longer than a rollout can take
- ended with an error — failed
- ended without an error — succeeded

A release that has been created but not yet applied SHALL be reported as queued rather than as
missing or erroneous, including a deployment awaiting payment.

#### Scenario: A deployment awaiting payment

- **WHEN** a deployment has been created but cannot yet be applied
- **THEN** its release is reported as queued

#### Scenario: A rollout in progress

- **WHEN** a rollout has begun and has not finished
- **THEN** its release is reported as in flight
- **AND** the deployment's applied release is still the previous one

### Requirement: The applied release is recorded on the deployment

A deployment SHALL carry a nullable reference to the release it is **running**, distinct from the
release it desires. The reconciler SHALL set it to the desired release on success, in the same
transaction that records the rollout's outcome.

On a failed rollout it SHALL be left unchanged, because an atomic rollback restores the previously
applied release and the unchanged value is therefore already correct. No component SHALL be
required to write a transition when a rollback restores an earlier release.

It SHALL be exposed on deployment reads, so that what a deployment is running can be asked without
deriving it — including across a listing of many deployments, where a per-deployment derivation
would be a query per row.

The desired reference SHALL NOT be read as what is running. Everything a caller needs about the
running rollout — its build, its template, its values — SHALL be reachable through the applied
reference.

#### Scenario: A rollout succeeds

- **WHEN** a rollout completes successfully
- **THEN** the deployment's applied release is the one that was just applied

#### Scenario: A rollout fails

- **WHEN** a rollout fails and is rolled back
- **THEN** the deployment still desires the release that failed
- **AND** the deployment's applied release is still the previously applied one
- **AND** no transition was written to make that so

#### Scenario: Asking what a listing is running

- **WHEN** many deployments are listed at once
- **THEN** each one's running release is available without a per-deployment derivation

#### Scenario: Retrying after a failure

- **WHEN** a failed deployment is reconciled again with no new request
- **THEN** the same desired release is applied again

### Requirement: A release freezes the deployment's vars when it is created
Creating a release SHALL bind, to that release, the var rows that are in the
deployment's head at that moment, in the same transaction that creates the release row.
Tombstoned keys SHALL NOT be bound.

Where the request that creates the release also submits vars, those vars SHALL be written
before the binding is taken, so the release captures them.

A var row SHALL be inserted only when the submitted value or sensitivity actually differs
from head. Without that, every rollout would append a complete copy of the configuration
and the history would stop being readable.

The binding, like every other release column, SHALL NOT be revised after it is written.

#### Scenario: A rollout captures the current vars
- **WHEN** a release is created for a deployment whose head holds three vars
- **THEN** that release is bound to those three var rows

#### Scenario: A rollout that also submits vars
- **WHEN** a release is created by a request that submits a changed var
- **THEN** the new value is written first
- **AND** the release is bound to the new value, not the previous one

#### Scenario: A rollout that changes nothing
- **WHEN** a release is created by a request submitting vars identical to head
- **THEN** no new var rows are written
- **AND** the release is bound to the existing rows

#### Scenario: A deleted key
- **WHEN** a release is created after a key was deleted
- **THEN** that key is not bound to the release

### Requirement: A failed rollout leaves the deployment's vars in place
Vars written by a request that creates a release SHALL remain the deployment's desired
state whether or not the resulting rollout succeeds, and SHALL be captured by the next
release.

This matches how the deployment's user values already behave: they are written when the
rollout is requested, not when it succeeds. Vars are desired state, and making them
conditional on a rollout's outcome would mean the platform stops recording what the user
asked for, leaving a retry with nothing to reconstruct intent from.

Nothing is lost: the failed release keeps its own binding, so what that release meant does
not change retroactively, and `pending` continues to report that the running pod does not
carry the change.

#### Scenario: A rollout fails
- **WHEN** a release carrying a changed var fails
- **THEN** head still holds the changed var
- **AND** the failed release's snapshot still resolves to what it was created with
- **AND** the deployment reports `pending` as true
