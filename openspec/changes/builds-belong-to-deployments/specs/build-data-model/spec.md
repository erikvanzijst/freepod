## REMOVED Requirements

### Requirement: Builds are owned by a user, not a deployment

**Reason**: A build is made for one deployment, and the platform can now say which. The
separation only existed because a first deploy had no deployment until a build had
produced its image; the placeholder image removed that constraint.

**Migration**: Existing builds are linked to the deployment that released them. Builds no
release ever used are deleted. Replaced by "A build belongs to a deployment".

## ADDED Requirements

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

## MODIFIED Requirements

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
