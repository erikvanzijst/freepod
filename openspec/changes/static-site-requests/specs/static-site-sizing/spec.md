## Purpose

How a static-site build reaches the release that runs it, and the smaller memory request
the `custom` chart renders for the application container of such a release.

## ADDED Requirements

### Requirement: The reconciler projects the release's build into system values

On every apply the reconciler SHALL inject `caelus.build.staticSite`, a boolean that is
true only when the release being applied names a succeeded build recording a static site,
and, when the release names a succeeded build, that build's image as `caelus.build.image`.
Both SHALL come from the build the release records, never from user values, and SHALL
take precedence over anything a tenant supplies.

#### Scenario: A release of a static-site build

- **WHEN** the release being applied names a succeeded build that records a static site
- **THEN** the system values carry `caelus.build.staticSite: true` and that build's image
  as `caelus.build.image`

#### Scenario: A release of another build

- **WHEN** the release names a succeeded build that does not record a static site
- **THEN** the system values carry `caelus.build.staticSite: false` and that build's image

#### Scenario: A release with no build

- **WHEN** the release names no build
- **THEN** the system values carry `caelus.build.staticSite: false` and no build image

#### Scenario: User values cannot claim a static site

- **WHEN** a deployment's user values carry `caelus.build` entries
- **THEN** the template's schema rejects them, and the injected system values would take
  precedence in any case

### Requirement: The custom chart sizes a static site's app container to its idle usage

The `custom` chart SHALL render its application container's resource requests from the
`staticSiteResources` system value when `image` is non-empty, `caelus.build.staticSite`
is true, and `caelus.build.image` equals `image`. In every other case it SHALL render
`resources`. Both SHALL be requests only. `staticSiteResources` SHALL request 16Mi of
memory, and `resources` SHALL request 128Mi. Both SHALL request the same CPU. Neither
value SHALL be settable through the tenant-facing schema.

#### Scenario: A static-site image gets the smaller request

- **WHEN** the chart renders an image that is the static-site build's own image
- **THEN** the application container requests 16Mi of memory and has no limits

#### Scenario: A different image keeps the default

- **WHEN** `caelus.build.staticSite` is true but `image` is not `caelus.build.image`
- **THEN** the application container requests 128Mi of memory

#### Scenario: A non-static build keeps the default

- **WHEN** `caelus.build.staticSite` is false
- **THEN** the application container requests 128Mi of memory

#### Scenario: The placeholder keeps the default

- **WHEN** `image` is empty
- **THEN** the placeholder container requests 128Mi of memory

#### Scenario: A deployment switches between static and non-static builds

- **WHEN** a deployment is released with a non-static build after a static-site build,
  or the other way round
- **THEN** each release renders the request that matches the build it runs
