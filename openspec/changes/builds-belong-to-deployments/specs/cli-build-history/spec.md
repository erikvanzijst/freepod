## REMOVED Requirements

### Requirement: The history is the account's builds, not a project's

**Reason**: Builds belong to a deployment, and a project records exactly one. The
account-wide listing existed only because the platform had no narrower answer, and it
buried a project's builds among every other project's.

**Migration**: Replaced by "The history is the project's builds". There is no
account-wide option.

### Requirement: The build a project is running is identified

**Reason**: It described marking a build within an account-wide listing, tolerating
every way of not having a project. The listing now requires one, so only the marking
survives.

**Migration**: Replaced by "The project's running build is marked".

## ADDED Requirements

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
