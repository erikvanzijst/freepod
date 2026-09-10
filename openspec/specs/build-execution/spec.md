# build-execution Specification

## Purpose
The contract honored by the container that performs a build: how it obtains the project
archive, produces an image, reports the result, and the boundaries it runs within given
that it executes code supplied by a tenant.
## Requirements
### Requirement: The build container holds no platform credentials

The build container SHALL NOT be given database credentials, Kubernetes API credentials,
or any long-lived registry or object-store credential.

The container executes tenant-supplied code: a project's dependency install scripts and
build commands run with full access to the container's environment. Any credential
present there is a credential handed to every tenant. This is why the build container
reports its result indirectly rather than writing to the database itself.

#### Scenario: No database access from the build container

- **WHEN** the build container's environment is inspected
- **THEN** it contains no database connection string or credential, and the database is unreachable from it

#### Scenario: No Kubernetes API access from the build container

- **WHEN** the build container attempts to reach the Kubernetes API
- **THEN** it has no credential to authenticate with

### Requirement: Network reach is restricted to what a build needs

The build container SHALL be permitted egress only to the object store, the container
registry, DNS, and public networks required to fetch dependencies. It MUST NOT be able to
reach the platform's own services or other tenants' workloads.

#### Scenario: Platform services are unreachable

- **WHEN** the build container attempts to connect to a platform service such as the database or the API
- **THEN** the connection is refused

#### Scenario: Dependency fetching still works

- **WHEN** a build installs dependencies from public package registries
- **THEN** those requests succeed

### Requirement: The artifact is retrieved with a time-limited credential

The build container SHALL retrieve its project archive using a credential supplied to it
that grants read access to that one object and expires.

#### Scenario: Artifact is retrieved and unpacked

- **WHEN** the build container starts with a valid artifact credential
- **THEN** it retrieves and unpacks the archive into its working directory

#### Scenario: Unretrievable artifact fails the build

- **WHEN** the artifact cannot be retrieved
- **THEN** the container terminates unsuccessfully, and the reason appears in its output

### Requirement: Archive extraction is constrained

The build container SHALL reject archive entries that would write outside the extraction
directory, and SHALL bound the total extracted size and entry count.

The archive is supplied by a tenant and is untrusted input. Path traversal entries,
absolute paths, escaping symbolic links, and decompression bombs must not be honored
merely because extraction happens inside a sandbox.

#### Scenario: Traversing entry is rejected

- **WHEN** an archive contains an entry resolving outside the extraction directory
- **THEN** extraction fails and the build terminates unsuccessfully

#### Scenario: Oversized archive is rejected

- **WHEN** an archive expands beyond the configured extracted-size or entry-count limit
- **THEN** extraction stops and the build terminates unsuccessfully

### Requirement: A project's own Dockerfile decides how it is built

When the extracted project contains a Dockerfile at its root, the build container SHALL
build that Dockerfile and SHALL NOT run stack detection. The project's Railpack
configuration is not read in this case, because it is input to a builder that did not
run.

A Dockerfile that fails to build MUST fail the build. The build container MUST NOT fall
back to stack detection, since a project that builds one way on Monday and another way
on Tuesday is indistinguishable from a platform fault.

The build MUST be granted no additional isolation entitlements, so a Dockerfile
instruction requiring them fails rather than widening what tenant code may do.

#### Scenario: Project with a Dockerfile builds from it

- **WHEN** a project containing a root Dockerfile is built
- **THEN** the image is produced from that Dockerfile and no stack detection is performed

#### Scenario: A failing Dockerfile fails the build

- **WHEN** a project's root Dockerfile cannot be built
- **THEN** the build terminates unsuccessfully and no image is published

#### Scenario: Dockerfile outranks Railpack configuration

- **WHEN** a project contains both a root Dockerfile and Railpack configuration
- **THEN** the image is produced from the Dockerfile and the Railpack configuration has no effect

#### Scenario: A Dockerfile requiring extra entitlements fails

- **WHEN** a root Dockerfile contains an instruction requiring a build entitlement the platform does not grant
- **THEN** the build terminates unsuccessfully and its output states which entitlement was refused

### Requirement: The platform chooses what interprets a Dockerfile

The component that reads a project's Dockerfile and drives the build daemon SHALL be
selected and version-pinned by the platform. A directive in the project that names a
different one MUST have no effect.

This is not a build step. Whatever interprets the Dockerfile emits build instructions of
its own choosing, names its own cache sources, and sits on the daemon's image-resolution
path — a wider capability than executing a build instruction, and one a tenant therefore
MUST NOT be able to select.

#### Scenario: A project's syntax directive is ignored

- **WHEN** a root Dockerfile names a different interpreter for itself
- **THEN** the platform's pinned one is used and the named one is never fetched

#### Scenario: Unsupported syntax fails clearly

- **WHEN** a root Dockerfile uses a feature the platform's pinned interpreter does not support
- **THEN** the build terminates unsuccessfully and its output states which instruction was not understood

### Requirement: The image is produced by zero-configuration detection

The build container SHALL detect the project's stack and produce a container image
without requiring a Dockerfile or any build configuration in the project. Detection
applies to a project that carries no Dockerfile at its root; a project that does carry
one is built from it instead.

The build plan and the component executing it MUST be version-matched, since the plan
format is a contract between them.

#### Scenario: Project without a Dockerfile builds

- **WHEN** a project in a supported stack is built and contains no Dockerfile
- **THEN** its stack is detected and an image is produced

#### Scenario: Undetectable project fails clearly

- **WHEN** a project's stack cannot be detected and it carries no root Dockerfile
- **THEN** the build terminates unsuccessfully and its output states that detection failed

### Requirement: The image is pushed under the owner's namespace and anchored by a tag

The build container SHALL push the produced image to a repository derived from the build's
owner, under a tag derived from the build identifier, and SHALL obtain the resulting
content digest.

The tag is never exposed through the API and nothing deploys by it. It exists so the
manifest is not left untagged: an untagged manifest is removable by a registry garbage
collection pass, which would silently break every deployment referencing it by digest.

#### Scenario: Image is pushed under the owner's repository

- **WHEN** a build succeeds for a given owner
- **THEN** the image is present in the registry under that owner's repository, reachable by its digest

#### Scenario: Pushed manifest is tagged

- **WHEN** a build succeeds
- **THEN** the pushed manifest carries a tag derived from the build identifier

### Requirement: A published image is checked against the runtime contract

After the image is published, the build container SHALL inspect it and SHALL report a
warning when the image is unlikely to serve traffic: when the port the platform assigns
is not among the image's declared ports, or when the image declares no command to run.

These checks MUST NOT fail the build. A declared port is a declaration rather than a
guarantee, and images that serve correctly without one exist; refusing them would reject
working builds to catch a guess.

#### Scenario: Image declaring a different port warns

- **WHEN** a published image declares ports and the platform's port is not among them
- **THEN** the build output warns that the image may not serve traffic, and the build succeeds

#### Scenario: Image with no command warns

- **WHEN** a published image declares neither an entrypoint nor a command
- **THEN** the build output warns that the image has nothing to run, and the build succeeds

#### Scenario: Conforming image is not warned about

- **WHEN** a published image declares the platform's port and a command to run
- **THEN** the build output contains no contract warning

### Requirement: The build reports its result without credentials

On success the build container SHALL report the produced image reference through its
termination status, in the form `{user_id}@{digest}`. On any failure it SHALL terminate
with a non-zero exit status.

#### Scenario: Successful build reports its image

- **WHEN** a build completes successfully
- **THEN** the container exits successfully and its termination status carries the image reference

#### Scenario: Failed build exits non-zero

- **WHEN** any stage of the build fails
- **THEN** the container exits with a non-zero status and reports no image

### Requirement: Build output names the builder that ran

The build container SHALL state, at the start of its output, which builder produced the
image. A tenant can read the log; they cannot read the platform's source, so the reason
their project built the way it did MUST be visible to them.

#### Scenario: Dockerfile build says so

- **WHEN** a project is built from its root Dockerfile
- **THEN** the build output states that the Dockerfile was used

#### Scenario: Detected build says so

- **WHEN** a project without a root Dockerfile is built
- **THEN** the build output states that the project's stack was detected

### Requirement: Build output is human-readable progress

The build container SHALL emit its progress to standard output as plain text without
terminal control sequences, since that output is stored and replayed to users verbatim.

#### Scenario: Output is free of control sequences

- **WHEN** a build's stored log is read
- **THEN** it contains plain readable text with no terminal escape sequences

