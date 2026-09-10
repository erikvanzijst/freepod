## ADDED Requirements

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

## MODIFIED Requirements

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
