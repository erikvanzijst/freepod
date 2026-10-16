## ADDED Requirements

### Requirement: A build records whether its image serves a static site

A build SHALL record whether its image serves a static site, as reported by its
container. It SHALL record a static site only when a successful build's report says so
explicitly. Every other build SHALL record not a static site, including builds that
finished before the platform recorded this, builds whose report omits it, and failed
builds. The value SHALL be held by the platform: no tenant request sets or changes it,
and the build API does not expose it.

#### Scenario: A static-site build records it

- **WHEN** a build succeeds and its report says the image serves a static site
- **THEN** the build records a static site

#### Scenario: A report without the verdict records not a static site

- **WHEN** a build succeeds and its report says nothing about a static site, or says
  something other than an explicit yes
- **THEN** the build records not a static site

#### Scenario: Builds from before this change are not static sites

- **WHEN** a build finished before the platform recorded this
- **THEN** it records not a static site
