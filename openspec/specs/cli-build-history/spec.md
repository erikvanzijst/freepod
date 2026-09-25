# cli-build-history Specification

## Purpose
Listing what the current project has built: its deployment's builds and no others, how
the build that deployment is running is marked, and what each row tells the reader.
## Requirements
### Requirement: The history is the project's builds

The client SHALL list the builds of the deployment the working directory's project
records, for the environment targeted, and no others.

Where there is no project file, the project belongs to another environment, or the
project records no deployment, the client SHALL refuse and say why, naming
`freepod deploy` where the project has simply not deployed yet. It SHALL NOT fall back to
listing anything else.

A project whose recorded deployment has since been deleted SHALL still have its builds
listed: builds outlive their deployment.

The client SHALL present the builds in the order the platform returns them, most recent
first, and SHALL NOT reorder them.

#### Scenario: Only this project's builds are listed

- **WHEN** the history runs in a project whose owner has also deployed other projects
- **THEN** only the builds of this project's deployment are listed

#### Scenario: Outside a project the history is refused

- **WHEN** the history runs where no project file exists
- **THEN** the client refuses and states that it lists a project's builds

#### Scenario: A project that has not deployed

- **WHEN** the project records no deployment
- **THEN** the client refuses and names `freepod deploy`

#### Scenario: A deleted deployment's builds are still listed

- **WHEN** the project records a deployment that has since been deleted
- **THEN** that deployment's builds are listed

#### Scenario: The platform's order is preserved

- **WHEN** the platform returns builds most recent first
- **THEN** they are presented in that order

### Requirement: The project's running build is marked

The client SHALL read the project's deployment and mark the listed build whose image it
is running, answering the question the history exists for: which of these builds is
serving traffic.

A deployment that is deleted, has never been applied, or runs an image none of the listed
builds produced SHALL yield an unmarked listing rather than a failure. The mark is a
convenience; the listing is the result.

Only a build producing the image the deployment runs SHALL be marked, and the meaning of
the mark SHALL be stated whenever one is shown.

#### Scenario: The deployed build is marked

- **WHEN** the project's deployment runs the image of a listed build
- **THEN** that build is marked and no other is

#### Scenario: A deleted deployment marks nothing

- **WHEN** the project's deployment has been deleted
- **THEN** its builds are listed with nothing marked

### Requirement: Each build reports its identity, outcome, timing, and image

Every listed build SHALL report its identifier, its status, when it was created, how
long it ran, and the image it produced.

The running time SHALL be measured from when the build started rather than from when it
was created: waiting for a worker is queueing, and counting it would report a short
build as a long one whenever the queue was busy. A build that has not started SHALL
report no running time, and one still running SHALL report the time elapsed so far.

Timestamps SHALL be presented in the reader's own timezone. A build that has produced no
image SHALL be shown as having none rather than being omitted.

#### Scenario: Queue time is not counted as build time

- **WHEN** a build waited for a worker before starting
- **THEN** the reported running time covers only the time since it started

#### Scenario: A running build reports elapsed time

- **WHEN** a build has started and not finished
- **THEN** the time elapsed since it started is reported

#### Scenario: A queued build reports no running time and no image

- **WHEN** a build has not yet started
- **THEN** it is listed with no running time and no image

### Requirement: Image references are abbreviated, and the abbreviation is marked

An image reference is dominated by its digest, which would otherwise make its column
wider than the rest of the listing together. The client SHALL abbreviate the digest,
SHALL mark the reference as truncated so no reader mistakes it for a complete one, and
SHALL offer the full reference on request.

A reference carrying no digest SHALL be shown as it is.

#### Scenario: A digest is shortened and marked

- **WHEN** a build's image reference carries a digest
- **THEN** the digest is shortened and the reference is marked as truncated

#### Scenario: The full reference is available

- **WHEN** the reader asks for full detail
- **THEN** image references are shown complete

### Requirement: The listing is bounded by default and says what it withheld

The client SHALL show a bounded number of the most recent builds by default, SHALL allow
that bound to be changed or lifted, and SHALL report how many builds were withheld
whenever it shows fewer than the account has. A bound that hides rows silently would
misrepresent the account's history.

A bound that could show nothing SHALL be refused as a usage error.

An account that has never built SHALL be told so, and no table SHALL be produced.

#### Scenario: A truncated listing says how much it withheld

- **WHEN** the account has more builds than the listing shows
- **THEN** the client reports how many of how many were shown, and how to see them all

#### Scenario: The bound can be lifted

- **WHEN** the reader asks for every build
- **THEN** all builds are listed and nothing is reported as withheld

#### Scenario: An account with no builds is told so

- **WHEN** the account has never built anything
- **THEN** the client says so and produces no table

### Requirement: The table is the result and everything else is a diagnostic

The client SHALL write the table to standard output, and SHALL write the explanation of
the mark, the withheld-build count, and every other remark to standard error, so that a
redirected listing carries rows and nothing else. Suppressing diagnostics SHALL leave
the table intact.

#### Scenario: A redirected listing carries only rows

- **WHEN** the listing is redirected
- **THEN** standard output carries the table
- **AND** the legend and counts do not appear in it

#### Scenario: Suppressing diagnostics keeps the table

- **WHEN** the listing runs with diagnostics suppressed
- **THEN** the table is still written to standard output
