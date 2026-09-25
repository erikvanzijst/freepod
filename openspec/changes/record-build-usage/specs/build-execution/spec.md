## ADDED Requirements

### Requirement: The build reports its resource usage

The build container SHALL measure its own resource consumption and report it through its
termination status, alongside its result, whether the build succeeded or failed: the CPU
time it consumed, its working-set memory integrated over the run, its peak memory, and the
time its run started and ended.

The measurement SHALL cover every process the build ran, including the image builder's
own, and SHALL use the container's own accounting rather than anything the tenant's
build instructions can influence.

Working-set memory SHALL exclude reclaimable file cache, matching the definition of
memory used for every other workload.

#### Scenario: A successful build reports its usage

- **WHEN** a build succeeds
- **THEN** its termination status carries its usage as well as its image

#### Scenario: A failed build reports its usage

- **WHEN** a build fails in a way that lets it report
- **THEN** its termination status carries its usage as well as the failure

#### Scenario: Child processes are counted

- **WHEN** the image builder does its work in processes of its own
- **THEN** their CPU time and memory are included in what the build reports
