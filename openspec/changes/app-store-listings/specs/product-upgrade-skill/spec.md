## ADDED Requirements

### Requirement: Every proposed upgrade adds a user-facing release entry
A session whose patch moves a product to a new version MUST add an entry for
the target version at the top of `products/catalog/<slug>/releases.yaml`,
creating the file when it is missing. The entry's notes MUST be a short
Markdown summary, written for the people who use the app, of what changed
across every upstream release the upgrade covers.

#### Scenario: Upgrade covering skipped releases
- **WHEN** a session upgrades Immich from `3.2.4` to `3.3.1`, covering
  `3.3.0` and `3.3.1`
- **THEN** its patch adds one `releases.yaml` entry with version `3.3.1`
  whose notes summarize the user-visible changes of both releases

#### Scenario: First upgrade of a product without releases
- **WHEN** a session upgrades a product whose folder has no `releases.yaml`
- **THEN** its patch creates the file with the new version as its only entry

### Requirement: Release entries stay user-facing and self-contained
Release notes MUST leave out contributor credits, links to upstream issues or
pull requests, @-mentions, and changes only operators or developers would
notice, and MUST be valid under the catalog's releases-file rules so that
`catalog lint` passes on the proposed patch.

#### Scenario: Upstream changelog with PR links
- **WHEN** the upstream changelog lists items as links to pull requests with
  author handles
- **THEN** the release entry describes those items in plain words without the
  links or handles

#### Scenario: Internal-only release
- **WHEN** every change in the covered releases is a dependency bump or a
  build fix
- **THEN** the entry says the update brings maintenance and security fixes,
  rather than listing them
