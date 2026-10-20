# Spec Delta

## Purpose

What the edge serves on the tenant domain's own names, and on hostnames tenants no longer
use. The tenant domain's apexes point visitors back to the platform, and each retired tenant
hostname permanently redirects to the one that replaced it.

## ADDED Requirements

### Requirement: The tenant domain's apex redirects to the platform

Each environment's tenant domain apex MUST permanently redirect to that environment's
platform origin over HTTPS, preserving nothing of the request path: `freepod.app` to
`https://freepod.eu` and `dev.freepod.app` to `https://dev.freepod.eu`. It MUST serve no
content of its own.

#### Scenario: The production apex

- **WHEN** a browser requests `https://freepod.app/anything`
- **THEN** it receives a permanent redirect to `https://freepod.eu`

#### Scenario: The development apex

- **WHEN** a browser requests `https://dev.freepod.app/`
- **THEN** it receives a permanent redirect to `https://dev.freepod.eu`

### Requirement: Retired tenant hostnames redirect to their replacements

Every hostname on the configured list of retired tenant hostnames,
`<app>.<handle>.<old domain>`, MUST permanently redirect to
`https://<app>-<handle>.<tenant domain>`, keeping the path and query. A request with any
method other than GET MUST be redirected with **308**, so its method and body are kept.

#### Scenario: A page request is redirected with its path

- **WHEN** a browser requests `https://photos.alice.freepod.eu/albums/7?sort=date`
- **THEN** it receives a permanent redirect to
  `https://photos-alice.freepod.app/albums/7?sort=date`

#### Scenario: A non-GET request keeps its method

- **WHEN** a client sends `POST https://photos.alice.freepod.eu/api/upload`
- **THEN** it receives **308** to `https://photos-alice.freepod.app/api/upload`

#### Scenario: Development hostnames map to the development tenant domain

- **WHEN** a browser requests `https://notes.bob.dev.freepod.eu/`
- **THEN** it receives a permanent redirect to `https://notes-bob.dev.freepod.app/`

#### Scenario: The redirect is served over valid TLS

- **WHEN** a client connects to a retired hostname over HTTPS
- **THEN** the handshake succeeds with a certificate valid for that name

### Requirement: The retired list is explicit and kept out of the repository

The redirects MUST match each retired hostname exactly, from a list configured per
environment in the infrastructure code. The list MUST be supplied from uncommitted
configuration, because it names tenants' applications. No pattern may redirect names that
are not on the list, so platform hosts beneath the old domain are never captured.

#### Scenario: A platform host is not captured

- **WHEN** a client requests `https://cr.dev.freepod.eu/`
- **THEN** it reaches the platform service at that name, not a redirect

#### Scenario: An unlisted name is not redirected

- **WHEN** a client requests `https://unknown.someone.freepod.eu/`
- **THEN** no tenant redirect answers it
