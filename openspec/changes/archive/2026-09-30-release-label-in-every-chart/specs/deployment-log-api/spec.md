## ADDED Requirements

### Requirement: A read follows the deployment by default and can be pinned to any release

The endpoint SHALL, by default, return the output of the deployment as a whole, continuing
across redeploys and container restarts, so that a caller following a running application
observes a rollover rather than the stream ending.

A caller SHALL be able to pin the read to a single release by its per-deployment number, in
which case only that release's output is returned.

Pinning SHALL work for a release whose pods no longer exist, including one that failed and was
rolled back. This is the case the endpoint exists to serve and SHALL NOT be treated as an
exceptional path.

Pinning SHALL be offered for every deployment, whatever its product. The endpoint SHALL NOT vary
its answer by chart.

A release that was applied before its product's chart rendered release labels has no labeled
output. A pinned read of such a release SHALL return an empty stream. This SHALL be the only
case in which a release that ran answers a pinned read with nothing, and it SHALL disappear
once the log store's retention has removed that release's output.

#### Scenario: A rollout happens while following

- **WHEN** a caller is following a deployment and a new release becomes live
- **THEN** the stream continues, carrying the new release's output

#### Scenario: Pinning to a failed release

- **WHEN** a caller requests the log of a release that failed and whose pods were deleted
- **THEN** that release's output is returned

#### Scenario: Pinning to a release of another deployment

- **WHEN** a caller names a release number that does not belong to the addressed deployment
- **THEN** the request is refused and no output from any other deployment is returned

#### Scenario: Pinning on a curated product

- **WHEN** a caller pins a read to a release of a deployment of any curated product
- **THEN** that release's output is returned
- **AND** the request is not refused as unsupported by the product

#### Scenario: Pinning to a release that never produced a pod

- **WHEN** a caller pins to a release that has not been applied, or that failed before any pod
  started
- **THEN** the caller is told that release produced no output because it never ran
- **AND** does not receive a silent empty stream indistinguishable from an application that
  printed nothing

## REMOVED Requirements

### Requirement: The default follows the deployment, not a release

**Reason**: Pinning no longer depends on the product, so the "attribution unavailable" answer and its scenarios are gone.

**Migration**: Replaced by "A read follows the deployment by default and can be pinned to any release". Clients that handled the unavailable response need no change, because it is no longer sent.
