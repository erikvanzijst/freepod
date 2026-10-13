# catalog-cli Specification

## Purpose


Defines the `caelus catalog apply|curate|lint` command surface, what each
verb guarantees, and why this group is intentionally exempt from the
repository's REST parity convention.

## Requirements


### Requirement: The CLI provides a catalog command group
The CLI SHALL provide a `catalog` command group exposing `apply`, `curate`, and
`lint`. There is no command to release a product from the catalog: that is
expressed by removing its catalog file, which the reconciler applies on the next
rollout. These commands are operator and build tooling rather
than tenant-facing API surface, so they SHALL be CLI-only and are exempt from
the REST parity convention. The write guard they rely on lives in the service
layer, so the protections they enforce remain identical across the REST API,
the CLI, and the admin UI.

#### Scenario: Catalog commands are available
- **WHEN** an admin runs the CLI help
- **THEN** the `catalog` command group SHALL be listed with its subcommands

#### Scenario: No REST equivalent is required
- **WHEN** the catalog commands are added
- **THEN** no corresponding REST endpoints SHALL be required for parity

### Requirement: Apply reconciles a catalog directory into the database
`catalog apply` SHALL read every product folder in a given catalog directory,
validate them, and apply them through the reconciler within a single
transaction. It SHALL support a dry-run mode that reports the actions it would
take — products created, products adopted, templates inserted, canonical
pointers moved, template versions stamped, screenshots materialized, and
releases inserted, updated or deleted — without writing to the database. A
validation or reconciliation failure SHALL cause a non-zero exit status and
leave the database unchanged.

#### Scenario: Apply reconciles the directory
- **WHEN** an admin runs `catalog apply` against a valid catalog directory
- **THEN** the catalog SHALL be reconciled and the command SHALL exit zero

#### Scenario: Dry run writes nothing
- **WHEN** an admin runs `catalog apply` in dry-run mode
- **THEN** the planned actions SHALL be reported
- **AND** the database SHALL be unchanged

#### Scenario: Dry run reports release changes
- **WHEN** an admin runs `catalog apply` in dry-run mode after a version was
  added to a product's `releases.yaml`
- **THEN** the report SHALL include the release it would insert

#### Scenario: Failure is atomic
- **WHEN** one catalog file in the directory is invalid
- **THEN** the command SHALL exit non-zero
- **AND** no changes from any file in that run SHALL be persisted

### Requirement: Curate generates catalog files from database state
`catalog curate` SHALL write a product's catalog folder, `<slug>/`, into the
catalog directory, derived from the current database state: its catalog
document and its icon, so that a hand-tuned product can be graduated into the
catalog without hand-authoring YAML. The document SHALL include the product's
listing text fields. Curate SHALL round-trip exactly: applying a generated
folder to the database it came from MUST match the existing template by spec
equality and insert no new template rows.

Writing the files SHALL NOT curate the product. Curation takes effect only when
the reconciler applies the committed catalog during a rollout, so the command
SHALL report the steps that remain, naming the files it wrote.

#### Scenario: Curate writes the catalog document and icon
- **WHEN** an admin runs `catalog curate` for a product with slug `photos`
- **THEN** the document SHALL be written to `photos/photos.yaml` in the
  catalog directory
- **AND** its icon SHALL be written into `photos/` at the path the document
  references

#### Scenario: Curate reports the remaining steps
- **WHEN** `catalog curate` completes
- **THEN** it SHALL report the files it wrote
- **AND** SHALL state that the change must be committed and merged before the
  product becomes curated

#### Scenario: Curate does not change product state
- **WHEN** `catalog curate` completes for a non-curated product
- **THEN** that product's `curated` flag and `slug` SHALL be unchanged

#### Scenario: Curate round-trips without churn
- **WHEN** a product is curated and the resulting file is applied to the same
  database
- **THEN** no new template row SHALL be inserted
- **AND** the product's canonical `template_id` SHALL be unchanged

#### Scenario: Curate targets a single product
- **WHEN** an admin runs `catalog curate` for a named product
- **THEN** only that product's catalog folder SHALL be written

#### Scenario: Generated upstream block requires completion
- **WHEN** a product's catalog document is generated
- **THEN** the emitted `upstream` block SHALL be present for the operator to
  complete, since release-detection metadata is not derivable from the database

### Requirement: Lint validates catalog files without a database
`catalog lint` SHALL validate a catalog directory using only the files
themselves, so it can run in continuous integration where no database or
cluster is reachable. It SHALL verify that the directory uses the per-product
folder layout, that each document parses, declares a supported
`schema_version`, has a slug matching its folder and filename, declares unique
slugs across the directory, does not declare `visibility`, contains a
`values_schema` that is a valid JSON Schema document, declares valid listing
fields, and declares an `upstream.match` expression that compiles and defines a
`version` capture group. It SHALL also verify that any referenced icon and
screenshot file exists inside the product's folder and can be processed as an
image, and that any `releases.yaml` is valid, so that a missing or corrupt
asset is caught in review rather than failing a rollout. It SHALL also verify
that the generated `catalog.schema.json` has not drifted from the Pydantic
models it is generated from; `catalog lint --write-schema` regenerates it.

#### Scenario: Lint passes on a valid catalog
- **WHEN** continuous integration runs `catalog lint` on a valid catalog
  directory
- **THEN** the command SHALL exit zero

#### Scenario: Lint rejects a missing icon file
- **WHEN** a catalog file references an icon path that does not exist in its
  product folder
- **THEN** `catalog lint` SHALL exit non-zero and identify the offending file

#### Scenario: Lint rejects a missing screenshot file
- **WHEN** a catalog file references a screenshot that does not exist in its
  product folder
- **THEN** `catalog lint` SHALL exit non-zero and identify the offending file

#### Scenario: Lint rejects an invalid releases file
- **WHEN** a product's `releases.yaml` lists a version twice
- **THEN** `catalog lint` SHALL exit non-zero and identify the file

#### Scenario: Lint rejects an invalid values schema
- **WHEN** a catalog file's `values_schema` is not a valid JSON Schema document
- **THEN** `catalog lint` SHALL exit non-zero and identify the offending file

#### Scenario: Lint requires no database
- **WHEN** `catalog lint` runs with no database configured
- **THEN** it SHALL complete validation without attempting a database
  connection
