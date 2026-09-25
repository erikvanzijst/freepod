## MODIFIED Requirements

### Requirement: Builds are created from an uploaded artifact

The system SHALL provide an authenticated endpoint that creates a build for a deployment
from a previously issued artifact identifier. The caller MUST supply only that
identifier; the deployment MUST be taken from the request path, and the owner from the
deployment. Neither MUST be accepted as request body input.

A build SHALL be refused for a deployment that is being deleted or has been deleted:
nothing can be released into it, so a build for it could only be wasted.

The system SHALL NOT refuse a build because of which product the deployment runs or
which values its chart declares. Whether a chart consumes an image is that chart's
concern, not the build path's.

#### Scenario: Build is created for an uploaded artifact

- **WHEN** a deployment's owner creates a build for it, referencing an artifact they uploaded
- **THEN** a build is created in `queued` status, belonging to that deployment, and its location is returned

#### Scenario: Owner is not taken from the request body

- **WHEN** a build creation request body includes a user or deployment identifier
- **THEN** that value is ignored or rejected, and the build belongs to the deployment named in the path

#### Scenario: A deleting or deleted deployment takes no builds

- **WHEN** a build is created for a deployment that is being deleted or has been deleted
- **THEN** the request is refused with a client error and no build is created

#### Scenario: Anonymous creation is refused

- **WHEN** an unauthenticated request attempts to create a build
- **THEN** the request is rejected and no build is created

### Requirement: Builds are readable only by their owner

The system SHALL scope build reads to builds of deployments the authenticated caller
owns. Administrators MAY read any build. A build belonging to another user's deployment,
or to a different deployment than the one addressed, MUST be indistinguishable from one
that does not exist.

#### Scenario: Owner reads their build

- **WHEN** a user requests a build of a deployment they own
- **THEN** the build's status, timestamps, artifact identifier, and image value are returned

#### Scenario: Another user's build is not found

- **WHEN** a user requests a build of a deployment owned by someone else
- **THEN** the response is indistinguishable from a request for a build that does not exist

#### Scenario: A build addressed under the wrong deployment is not found

- **WHEN** a build is requested under a deployment other than its own
- **THEN** the response is indistinguishable from a request for a build that does not exist

## REMOVED Requirements

### Requirement: A user can list their own builds

**Reason**: Builds belong to deployments. An account-wide listing answers a question no
client asks, and the one client that listed it did so only because nothing narrower
existed.

**Migration**: List a deployment's builds instead; replaced by "A deployment's builds can
be listed".

### Requirement: Builds are addressed under their owning user

**Reason**: A build's position in the resource hierarchy is under its deployment, which is
itself under its owner.

**Migration**: Replaced by "Builds are addressed under their deployment". Clients using
the account-level paths must be upgraded.

## ADDED Requirements

### Requirement: A deployment's builds can be listed

The system SHALL provide an endpoint listing the builds of the deployment named in the
request path, most recent first, including builds of a deployment that has since been
deleted. Builds of other deployments MUST NOT appear. A deployment's owner MAY list its
builds; administrators MAY list any deployment's builds.

Without enumeration a client can only ever reference a build whose identifier it still
holds, so a previously produced image becomes unreachable once the client forgets it —
which is what a redeploy or a rollback needs.

#### Scenario: Owner lists a deployment's builds

- **WHEN** a deployment's owner lists its builds
- **THEN** that deployment's builds are returned, most recent first

#### Scenario: Listing excludes other deployments' builds

- **WHEN** builds are listed for one deployment while the same owner has builds for others
- **THEN** only the named deployment's builds are returned

#### Scenario: A non-administrator cannot list another user's builds

- **WHEN** a non-administrator lists builds of a deployment owned by another user
- **THEN** the request is refused as forbidden

### Requirement: Builds are addressed under their deployment

The system SHALL address every build endpoint — creating, listing, reading one, and
reading its log — under the deployment the build belongs to, which is itself addressed
under its owner. The platform's existing self-or-administrator guard on the owner in the
path SHALL apply unchanged.

The previous account-level build paths SHALL cease to exist rather than remaining as
aliases. A client built against them is not partially compatible — it must be upgraded —
and leaving the old paths answering would hide that from the very clients that need to
know.

#### Scenario: Builds are reached under their deployment

- **WHEN** a client acts on builds
- **THEN** the request is addressed under the owning user and the deployment, and both scope it

#### Scenario: The account-level build paths are gone

- **WHEN** a client requests a former account-level build path
- **THEN** no build endpoint answers it

#### Scenario: Acting under another account is refused

- **WHEN** a non-administrator addresses a build endpoint under another user's account
- **THEN** the request is refused as forbidden, before any build is created or read
