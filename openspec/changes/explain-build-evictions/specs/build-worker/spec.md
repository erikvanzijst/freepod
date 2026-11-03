## MODIFIED Requirements

### Requirement: A build's outcome is taken from its Job

The worker SHALL determine a build's outcome from the state of its Kubernetes Job, never
from the worker's own in-memory state, and SHALL record the image reported by a successful
Job.

When a failed Job's pod was evicted, the worker SHALL end the build's log with one line
explaining the eviction in the tenant's terms: the limit the build outgrew, or that the
platform stopped it. The line SHALL NOT carry the node's thresholds, available capacity, or
other workloads' names, which the eviction message itself contains.

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
