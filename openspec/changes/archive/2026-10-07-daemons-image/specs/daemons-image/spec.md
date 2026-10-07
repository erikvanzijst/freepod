## Purpose

One container image carries every Go daemon the platform runs. This capability defines
what that image contains, how it is versioned and published, and how each consumer
selects a daemon and pins a version independently of the others.

## ADDED Requirements

### Requirement: One image carries every platform Go daemon

Every Go daemon the platform runs SHALL be built from its own directory under
`daemons/` in this repository, and SHALL be shipped in a single image,
`ghcr.io/erikvanzijst/freepod/daemons`. Each daemon SHALL be a separate executable,
named after its directory, at the image root (`/app-auth`, `/ssh-auth`, …).

Every daemon directory under `daemons/` SHALL be included. Adding a daemon SHALL NOT
need a new image, a new publishing step or a new registry package.

The image SHALL contain the daemons' executables and the CA certificates they use to
verify TLS, and nothing else: no shell, no package manager, no credential, key or
tenant data. Its processes SHALL run as a non-root user.

#### Scenario: Every daemon is in the image
- **WHEN** a version of the image is built
- **THEN** it contains one executable for each daemon directory under `daemons/`, named
  after that directory

#### Scenario: Nothing beyond the daemons
- **WHEN** the published image is inspected
- **THEN** it contains the daemon executables and CA certificates only, with no shell,
  no credential and no key

#### Scenario: Non-root
- **WHEN** a consumer runs a daemon from the image without overriding the user
- **THEN** the process does not run as root

### Requirement: A consumer names the daemon it runs

The image SHALL NOT have a default command. Each consumer SHALL name the executable it
runs. A consumer that names none SHALL fail to start rather than run some other daemon.

#### Scenario: Consumer selects its daemon
- **WHEN** the SSH edge's resolver container runs the image with `/ssh-auth` as its
  command
- **THEN** it runs the SSH auth resolver and no other daemon

#### Scenario: No command
- **WHEN** a container runs the image without naming a command
- **THEN** it fails to start

### Requirement: The image is versioned in the repository and never re-pushed

The image's version SHALL be declared in the `daemons/` build context. That
declaration SHALL be the only input the publishing path derives the tag from. A change
to any daemon that is meant to ship SHALL be a new version.

An already-published version SHALL NOT be overwritten. The publishing path SHALL
enforce this: a publish of a version the registry already holds SHALL fail when run by
hand. When CI runs it, it SHALL be skipped as already published.

#### Scenario: Re-push refused
- **WHEN** an operator publishes a version the registry already holds
- **THEN** the publish fails and the published image is unchanged

#### Scenario: CI publishes a new version
- **WHEN** a commit reaches `master` declaring a version the registry does not hold, and
  every daemon's tests pass
- **THEN** CI publishes the image at that version

#### Scenario: CI skips a published version
- **WHEN** a commit reaches `master` declaring a version the registry already holds
- **THEN** CI publishes nothing and does not fail

### Requirement: Each consumer pins its own exact version

Every consumer SHALL reference the image by an exact version tag. No consumer SHALL use
a moving tag.

Each consumer's version SHALL be pinned independently. A new version SHALL reach a
daemon only when that daemon's own pin is moved to it. Publishing a version for one
daemon SHALL NOT change what any other daemon runs, and restarting the platform's
other workloads SHALL NOT change it either. Daemons on an authentication path SHALL
move only when they are deliberately repointed.

#### Scenario: Another daemon's release
- **WHEN** a new version is published for the sake of one daemon
- **THEN** every other daemon keeps running the version its pin names, through
  restarts and rollouts

#### Scenario: Rollback
- **WHEN** a daemon's pin is moved back to an earlier version
- **THEN** it runs that version's executable, which was never overwritten

### Requirement: Every daemon is checked before the image publishes

Every daemon module under `daemons/` SHALL be vetted and tested in CI. Publishing the
image SHALL depend on all of them passing. A daemon added under `daemons/` SHALL be
checked without editing CI.

#### Scenario: A daemon's test fails
- **WHEN** any daemon module's vet or tests fail on `master`
- **THEN** the image is not published

#### Scenario: A new daemon is checked
- **WHEN** a new daemon directory is added under `daemons/`
- **THEN** CI vets and tests it with no change to the workflow
