## MODIFIED Requirements

### Requirement: The build container holds no platform credentials

The build container SHALL NOT be given database credentials, Kubernetes API credentials,
or any long-lived registry or object-store credential.

The container executes tenant-supplied code: a project's dependency install scripts and
build commands run with full access to the container's environment. Any credential
present there is a credential handed to every tenant. This is why the build container
reports its result indirectly rather than writing to the database itself.

What the container MAY hold is a **capability**: an authorization that is minted for one
build, names exactly what that build may reach, and expires with it. The registry
authorization a build needs in order to push is such a capability, and it MUST be handed
to the container directly rather than as a credential the container could exchange for a
different or broader one. Its bounds are defined by `registry-authorization`.

The distinction is what makes the requirement enforceable rather than aspirational. A
build cannot produce an image without being able to write one somewhere, so "no
credential at all" was never achievable for the registry; what is achievable is that
everything the container holds is already scoped to work the tenant could do anyway, and
stops working when the build ends.

#### Scenario: No database access from the build container

- **WHEN** the build container's environment is inspected
- **THEN** it contains no database connection string or credential, and the database is unreachable from it

#### Scenario: No Kubernetes API access from the build container

- **WHEN** the build container attempts to reach the Kubernetes API
- **THEN** it has no credential to authenticate with

#### Scenario: The registry authorization is scoped and expiring

- **WHEN** the build container's registry authorization is inspected
- **THEN** it names only that build's own repositories and the images every build reads, and it expires with the build

#### Scenario: The container cannot obtain a broader authorization

- **WHEN** the build container attempts to exchange what it holds for authorization over any other repository
- **THEN** it holds nothing that can be exchanged, and the attempt yields no additional access
