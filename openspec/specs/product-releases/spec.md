# product-releases Specification

## Purpose

Record which upstream version each template deploys, when each version became
available on Freepod, and user-facing release notes per version, so the app
pages can show the current version, its date and what changed.

## Requirements

### Requirement: Template rows record the product version
A `product_template_version` row SHALL carry a nullable `version`: the
upstream version it deploys, as captured by the `version` group of its catalog
document's `upstream.match` applied to the value at `upstream.version_path`.
Rows the catalog did not produce, and rows whose value does not match, SHALL
have a null version. `version` SHALL NOT take part in template spec matching.

#### Scenario: Version from an image tag
- **WHEN** a catalog document's `version_path` points at an image tag of
  `v3.3.1` and its `match` is `^v(?P<version>.+)$`
- **THEN** the template row's `version` is `3.3.1`

#### Scenario: Value does not match
- **WHEN** the value at `version_path` does not match `upstream.match`
- **THEN** the template row's `version` is null

#### Scenario: Version does not split templates
- **WHEN** two documents differ only in how their version would be derived
  but have the same template spec
- **THEN** they match the same template row

### Requirement: Template reads include the version
Every template read, including a product's canonical template, SHALL include
the template's `version`.

#### Scenario: Canonical template version
- **WHEN** a client reads a product whose canonical template has version
  `3.3.1`
- **THEN** the product's `template` carries `version` `3.3.1`

### Requirement: The listing reports the current version and its availability date
A product's listing SHALL include `version`, the canonical template's version,
and `version_available_at`, the earliest `created_at` among the product's
non-deleted template rows with that same version. Both SHALL be null when the
canonical template has no version.

#### Scenario: Chart bump keeps the date
- **WHEN** a product moved to version `3.3.1` on day 1 and a new template with
  the same version but a different chart version became canonical on day 5
- **THEN** the listing reports `version` `3.3.1` and `version_available_at` on
  day 1

#### Scenario: Product without a version
- **WHEN** a product's canonical template has a null version
- **THEN** the listing reports null `version` and `version_available_at`

### Requirement: Releases are stored per product and version
A `product_release` row SHALL hold a product, a version, Markdown `notes`, and
its position among the product's releases (newest first). The pair of product
and version SHALL be unique.

#### Scenario: Duplicate version is refused
- **WHEN** a second release is recorded for a product and version that already
  has one
- **THEN** the write fails rather than storing two releases for that version

### Requirement: The API lists a product's releases
`GET /api/products/{product_id}/releases` SHALL return a plain JSON array of
the product's releases, newest first and unpaginated, each with `version`,
`notes` and `available_at` (the earliest template `created_at` with that
version, or null when no template carries it). It SHALL be readable by the
same callers as the product itself.

#### Scenario: Anonymous visitor reads releases
- **WHEN** an anonymous client requests the releases of a public product
- **THEN** it receives the product's releases, newest first

#### Scenario: Release older than version tracking
- **WHEN** a release's version is carried by no template row
- **THEN** that release is returned with a null `available_at`

#### Scenario: Product without releases
- **WHEN** a product has no release rows
- **THEN** the endpoint returns an empty list

### Requirement: Releases are written only by the catalog reconciler
Release rows SHALL be created, changed and removed only by the catalog
reconciler. No API or CLI command SHALL write them.

#### Scenario: No write endpoint exists
- **WHEN** a client sends a POST, PUT or DELETE to a product's releases path
- **THEN** the request is rejected as an unsupported method

### Requirement: The CLI lists releases at parity with the API
A `list-product-releases` command SHALL print a product's releases in the same shape
and order as the API endpoint.

#### Scenario: CLI lists releases
- **WHEN** an operator runs `list-product-releases` for a product with two releases
- **THEN** the command prints both releases, newest first, as YAML

### Requirement: A migration adds version tracking and releases
An Alembic migration SHALL add the nullable `version` column to
`product_template_version` and create the `product_release` table, and SHALL
provide a downgrade that removes both. Existing template rows SHALL get a null
version; the reconciler fills in derivable versions on its next run.

#### Scenario: Upgrade on existing templates
- **WHEN** the migration runs on a database with template rows
- **THEN** every template row has a null `version` and no release rows exist
