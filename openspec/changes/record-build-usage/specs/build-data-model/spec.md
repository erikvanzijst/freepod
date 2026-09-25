## ADDED Requirements

### Requirement: A build records its measured usage and whether it reached the ledger

A build SHALL record the resource usage its container reported — CPU time, integrated
working-set memory, peak memory, and the start and end of its run — and whether those
values were measured or estimated. It SHALL record when its usage was written to the usage
ledger, null until then.

These values SHALL be recorded when the worker observes the build finish, because the
container's report does not outlive the Job.

#### Scenario: Usage is stored when the build finishes

- **WHEN** the worker observes a build's Job finish with a usage report
- **THEN** the build records that usage, marked as measured

#### Scenario: A build awaiting recording is identifiable

- **WHEN** a build has finished but its usage has not been written to the ledger
- **THEN** it records no ledger time, and that alone identifies it as pending
