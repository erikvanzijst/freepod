## ADDED Requirements

### Requirement: The build reports whether its image serves a static site

On success the build container SHALL report, alongside the image reference, whether the
image serves a static site with the zero-configuration builder's own web server. It SHALL
report a static site only when the build plan's deploy start command is exactly one the
builder emits for a static site, and SHALL report anything else as not a static site.
Determining this SHALL NOT fail a build that otherwise succeeded.

#### Scenario: A detected static site is reported as one

- **WHEN** a project without a root Dockerfile is detected as a static site and builds
  successfully
- **THEN** the termination status carries the image and reports a static site

#### Scenario: A detected single-page app is reported as a static site

- **WHEN** a JavaScript single-page app is detected and served by the builder's own web
  server
- **THEN** the termination status reports a static site

#### Scenario: A detected server application is not a static site

- **WHEN** a project is detected as an application that runs its own server process
- **THEN** the termination status reports not a static site

#### Scenario: A Dockerfile build is never a static site

- **WHEN** a project is built from its root Dockerfile
- **THEN** the termination status reports not a static site, whatever the image runs

#### Scenario: A start command the project configured is not a static site

- **WHEN** the project configures its own start command, even one that starts the same
  web server
- **THEN** the termination status reports not a static site unless the command is
  exactly the builder's own

#### Scenario: An unreadable plan is not a static site

- **WHEN** the build plan cannot be read or does not have the expected shape
- **THEN** the build still succeeds and reports not a static site
