# build-worker Specification

## Purpose
The process that turns queued build records into running Kubernetes Jobs, mirrors their
output, records their outcome, and recovers builds whose worker or Job did not finish
cleanly.
## Requirements
### Requirement: Build processing is isolated from deployment reconciliation

Builds SHALL be processed by a worker separate from the deployment reconcile worker, with
its own process lifecycle and its own concurrency limit.

A build takes minutes. Sharing the reconcile worker's pool would let builds starve
deployment rollouts, and the reconcile queue's one-open-job-per-deployment constraint is
meaningless for builds, which are expected to run concurrently.

#### Scenario: Builds do not consume reconcile capacity

- **WHEN** several builds are running
- **THEN** deployment reconcile jobs continue to be claimed and processed at their normal rate

### Requirement: The worker advances all builds in a single non-blocking pass

The worker SHALL operate as a repeating pass that, on each iteration, claims newly queued
builds, advances every build already `running`, and applies the recovery rules below. No
step of a pass may block for the duration of a build.

Because every pass visits every `running` build, recovery is not a separate activity that
could be starved: a build whose previous worker went away is picked up by the next pass
with its true outcome. A worker restart therefore costs at most a gap in captured output,
not a lost build.

#### Scenario: Progress continues while builds are in flight

- **WHEN** builds are running
- **THEN** each pass still occurs at its normal interval, claiming, advancing, and recovering builds

#### Scenario: Progress continues when at capacity

- **WHEN** the number of running builds has reached the in-flight limit
- **THEN** passes still occur and running builds are still advanced and recovered, though no new build is claimed

#### Scenario: Worker restart does not strand a build

- **WHEN** a worker stops while builds are running and a worker later resumes
- **THEN** the next pass advances those builds from their Kubernetes Jobs

### Requirement: Concurrent builds are capped

The worker SHALL NOT claim a queued build while the number of builds already `running` has
reached a configured in-flight limit. Queued builds beyond the limit MUST remain `queued`
and be claimed by a later pass.

The limit bounds how much of the cluster's capacity builds may consume at once, which
matters because builds compete directly with tenant workloads for CPU and memory.

#### Scenario: Build is not claimed while at the limit

- **WHEN** a build is queued and the in-flight limit is already reached
- **THEN** the build remains `queued` and no Kubernetes Job is created for it

#### Scenario: Queued build is claimed once capacity frees

- **WHEN** a running build reaches a terminal status and a queued build is waiting
- **THEN** a later pass claims the queued build

### Requirement: Queued builds are claimed atomically

The worker SHALL claim the oldest `queued` build, transitioning it to `running` and
recording its start time in a single atomic operation, such that no build is ever claimed
by two workers.

#### Scenario: Oldest queued build is claimed first

- **WHEN** several builds are queued
- **THEN** the worker claims the one created earliest

#### Scenario: Concurrent workers never double-claim

- **WHEN** multiple workers attempt to claim simultaneously
- **THEN** each queued build is claimed by at most one worker

### Requirement: Each build runs as its own Kubernetes Job

The worker SHALL create one Kubernetes Job per build, in a namespace dedicated to builds,
and SHALL supply the build's identity and a time-limited credential for retrieving its
artifact.

The Job MUST be identifiable both by a name derived from the build and by a label carrying
the build identifier.

The build must be marked `running` before its Job is created, and the Job's identifier
recorded after. A worker that dies between those points therefore leaves a `running` build
with no Job identifier, which is unambiguously recoverable.

#### Scenario: Job is created for a claimed build

- **WHEN** the worker claims a build
- **THEN** a Kubernetes Job is created in the builds namespace, carrying the build identifier as a label, and the build records that Job's identifier

#### Scenario: Worker dies before creating the Job

- **WHEN** a worker marks a build `running` and stops before creating its Job
- **THEN** the build has no Job identifier and is recoverable as a failure

### Requirement: The build's stored output mirrors its Job's output

On each pass the worker SHALL read a running build's Job output and store it as the
build's log, so a client polling the log observes output while the build is still running.

The stored log is a mirror of the Job's current output, not an incrementally appended
stream. Re-reading in full is idempotent and needs no offset bookkeeping, so a worker that
restarts mid-build resumes correctly with no reconciliation of its own position.

Because a container runtime may rotate away older output, a read that returns less than
what is already stored MUST NOT shorten the stored log.

#### Scenario: Output is visible while the build runs

- **WHEN** a build is producing output
- **THEN** a client polling the build's log observes that output before the build finishes

#### Scenario: Worker restart does not corrupt the log

- **WHEN** a worker stops and resumes while a build is running
- **THEN** the stored log continues to reflect the Job's output, without duplicated or missing sections

#### Scenario: Rotated-away output does not shorten the stored log

- **WHEN** a read of a Job's output returns less than what is already stored for that build
- **THEN** the stored log is left unchanged

### Requirement: A build's outcome is taken from its Job

The worker SHALL determine a build's outcome from the state of its Kubernetes Job, never
from the worker's own in-memory state, and SHALL record the image reported by a successful
Job.

When a failed Job's pod was evicted, the worker SHALL end the build's log with one line
explaining the eviction in the tenant's terms: the limit the build outgrew, or that the
platform stopped it. The line SHALL NOT carry the node's thresholds, capacity, or other
workloads' names.

#### Scenario: Successful Job yields a succeeded build

- **WHEN** a running build's Job has completed successfully and reports an image reference
- **THEN** the build is recorded as `succeeded` with that image and a finish time

#### Scenario: Failed Job yields a failed build

- **WHEN** a running build's Job has terminated unsuccessfully
- **THEN** the build is recorded as `failed` with a finish time and no image

#### Scenario: Successful Job that reports no image is a failure

- **WHEN** a running build's Job has completed successfully but reports no usable image reference
- **THEN** the build is recorded as `failed`

#### Scenario: Build whose Job is gone is failed

- **WHEN** a running build's Job no longer exists
- **THEN** the build is recorded as `failed`, indicating its result could not be recovered

#### Scenario: Build with no Job identifier is failed

- **WHEN** a running build has no Job identifier
- **THEN** the build is recorded as `failed`

#### Scenario: A build that outgrows its storage says which limit

- **WHEN** a running build's pod is evicted for exceeding one of its own storage bounds
- **THEN** the build is recorded as `failed`
- **AND** its log ends with a line naming that bound's size and saying to make the build smaller

#### Scenario: A build stopped by node pressure says it is not the tenant's fault

- **WHEN** a running build's pod is evicted, or refused admission, because its node ran short of a resource
- **THEN** the build is recorded as `failed`
- **AND** its log ends with a line saying the platform stopped the build and to start it again, without naming the node's thresholds or other workloads

#### Scenario: A gate failure takes precedence over an eviction

- **WHEN** a build's egress gate gave up and its pod also carries an eviction
- **THEN** its log ends with the gate's line only

### Requirement: Builds exceeding their deadline are terminated

A build's Kubernetes Job SHALL carry an execution deadline enforced by Kubernetes itself,
so an over-running build is terminated whether or not a worker is running.

The worker SHALL additionally delete the Job of any build still active past that deadline
plus a grace period, as a backstop for a Job that outlived its own deadline.

Kubernetes is the primary enforcer because it is the only participant guaranteed to be
present. The worker needs no special handling for a healthy build that over-runs: the Job
terminates, and the ordinary outcome path above records the failure.

#### Scenario: Over-running build is terminated by Kubernetes

- **WHEN** a build exceeds its execution deadline
- **THEN** Kubernetes terminates its Job, and the next pass records the build as `failed`

#### Scenario: Job outliving its own deadline is deleted by the worker

- **WHEN** a running build's Job is still active past its deadline plus the grace period
- **THEN** the worker deletes the Job and records the build as `failed`

#### Scenario: Build within its deadline is left alone

- **WHEN** a build is running, its Job is active, and the deadline has not passed
- **THEN** neither the Job nor the build record is altered

