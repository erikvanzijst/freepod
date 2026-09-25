## Purpose

How a finished build's resource consumption becomes usage ledger samples: when it is
recorded, in which windows, with which quantities, and what is recorded when the build's
own measurements are missing.

## ADDED Requirements

### Requirement: A finished build's usage is recorded once its windows have settled

The system SHALL record the usage of every build that ran a Kubernetes Job and reached a
terminal status, succeeded or failed, into the usage ledger.

A build's usage SHALL be recorded only once every window its run spans has closed and the
ledger's settling allowance has elapsed after the last of them, so that no window still in
progress is ever recorded.

A build that never ran a Job consumed nothing measurable and SHALL record nothing. Builds
that had already finished when recording was introduced SHALL NOT be recorded at all.

#### Scenario: A failed build is recorded too

- **WHEN** a build whose Job ran ends as `failed`
- **THEN** its usage is recorded, exactly as a succeeded build's would be

#### Scenario: The current window is not recorded early

- **WHEN** a build finishes at 14:10
- **THEN** nothing is recorded for it until the 14:00–15:00 window has closed and settled

#### Scenario: A build that never got a Job records nothing

- **WHEN** a build is failed before any Job was created for it
- **THEN** no usage is recorded for it

#### Scenario: Builds that finished before recording existed are never recorded

- **WHEN** usage recording is introduced
- **THEN** every build already finished at that moment is treated as recorded, and no
  usage is written for any of them

### Requirement: A build's usage is recorded exactly once, whatever fails

Recording a build's usage and marking it recorded SHALL happen atomically. The work
still to be done SHALL be derivable from stored records alone, so that no state held by
a running process is needed to complete it.

#### Scenario: The worker restarts before recording

- **WHEN** the worker restarts after a build finished but before its usage was recorded
- **THEN** a later pass records it, with the same values

#### Scenario: Two passes race

- **WHEN** two passes attempt to record the same build
- **THEN** its samples are recorded once, and neither pass fails

#### Scenario: A crash mid-record leaves nothing half-written

- **WHEN** recording is interrupted partway
- **THEN** neither the samples nor the recorded mark persist, and a later pass records the build in full

### Requirement: Usage is split across the windows the build ran in

A build's usage SHALL be recorded in every ledger window its run overlaps, each window
receiving the share of the build's totals proportional to the part of the run that fell
within it.

The run SHALL be the start and end the build itself reported where available, since the
times the worker observed a build starting and finishing include the worker's own polling
delay.

#### Scenario: A build within one hour

- **WHEN** a build runs from 14:10 to 14:12
- **THEN** all of its usage is recorded in the 14:00 window

#### Scenario: A build across an hour boundary

- **WHEN** a build runs from 14:59 to 15:01
- **THEN** its usage is recorded half in the 14:00 window and half in the 15:00 window,
  and the two halves sum to its totals

### Requirement: Billable usage is floored at the build's requests

The billable CPU and memory quantities recorded for a build SHALL be, for each window, the
greater of the build's requested allowance held for the time it ran in that window and
the usage it measured in that window — the same floor applied to every other workload's
billable usage.

#### Scenario: A light build is billed at its requests

- **WHEN** a build used less CPU than it requested
- **THEN** its billable CPU is its request for the time it ran

#### Scenario: A heavy build is billed at what it used

- **WHEN** a build used more CPU than it requested
- **THEN** its billable CPU is what it measured

### Requirement: A build's allowances and runtime are recorded alongside its usage

For each window, a build SHALL record the same set of quantities recorded for any
container: its billable CPU and memory, its average CPU and memory usage, its requested
and limited CPU and memory, and how long it ran.

#### Scenario: Request and usage can be compared

- **WHEN** a build's samples for a window are read
- **THEN** its measured usage and its requests and limits are all present

### Requirement: Missing measurements are estimated at the build's requests

Where a build ran a Job but its own measurements are unavailable — it was killed before it
could report, its report was lost, or it was built by a builder that does not report — its
usage SHALL be recorded at its requested CPU and memory for the time the worker observed
it running, and the build SHALL be marked as estimated rather than measured.

#### Scenario: An OOM-killed build

- **WHEN** a build's container is killed without reporting its usage
- **THEN** its requests over its observed run are recorded, and the build is marked estimated

### Requirement: Build usage is attributed through the build's deployment

A build's usage SHALL be recorded against a subject of kind `build`, identified by the
build, attributed to the deployment the build belongs to. Its owner, product and
application SHALL therefore be those of that deployment in every report, and SHALL remain
so after the deployment is deleted.

#### Scenario: A build appears under its application

- **WHEN** usage is reported by application for the build's owner
- **THEN** the build's cost is included in its deployment's

#### Scenario: A deleted deployment keeps its builds' usage

- **WHEN** a deployment is deleted and a past period is reported
- **THEN** its builds' usage remains attributed to it
