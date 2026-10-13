# catalog-reconciliation Specification

## Purpose


Defines `CatalogReconciler` semantics: matching templates by spec equality,
inserting and repointing without ever mutating history, adopting existing
non-curated products, materializing icons, uncurating when a catalog file is
removed, and how the catalog is applied during rollout.

## Requirements


### Requirement: The reconciler matches templates by spec equality
The `CatalogReconciler` SHALL determine whether a catalog file's template
already exists by comparing a hash computed over exactly these template fields:
`chart_ref`, `chart_version`, `chart_digest`, `system_values_json`, and
`values_schema_json`. The hash MUST be computed from a canonical serialization
with sorted object keys, so that key ordering in the source YAML cannot affect
the result. Matching SHALL ignore how a template row was originally created.

#### Scenario: Existing template matches the catalog spec
- **WHEN** a non-deleted template for the product has the same values for all
  five spec fields as the catalog file
- **THEN** the reconciler SHALL reuse that template and SHALL NOT insert a new
  row

#### Scenario: Key ordering does not affect matching
- **WHEN** a catalog file declares `system_values` with keys in a different
  order than the stored template's `system_values_json`
- **THEN** the hashes SHALL be equal and no new template row SHALL be inserted

#### Scenario: Hand-authored template matches the catalog spec
- **WHEN** the only matching template was created through the admin UI and has
  a null `catalog_commit`
- **THEN** the reconciler SHALL reuse it rather than inserting a duplicate

### Requirement: The reconciler inserts templates and repoints the canonical
The reconciler SHALL insert a new `ProductTemplateVersion` carrying the
catalog's spec fields when no non-deleted template for the product matches that
spec. After matching or inserting, the reconciler SHALL set
`product.template_id` to the matched or inserted template's id.

#### Scenario: New spec produces a new template
- **WHEN** a catalog file's `system_values.image.tag` changes from `v3.0.3` to
  `v3.1.0` and no existing template matches
- **THEN** the reconciler SHALL insert a new template row
- **AND** SHALL set the product's `template_id` to the new row's id

#### Scenario: Reconciliation is idempotent
- **WHEN** the reconciler runs twice against an unchanged catalog
- **THEN** the second run SHALL insert no rows and SHALL leave
  `product.template_id` unchanged

### Requirement: The reconciler never mutates or deletes template rows
The reconciler SHALL treat `product_template_version` as append-only. It MUST
NOT update the spec fields of an existing template row and MUST NOT set
`deleted_at` on a template row. Removing a product from the catalog SHALL
uncurate it and delete nothing, leaving its template rows intact as history for
deployments that reference them. The only write the reconciler MAY make to an
existing template row is filling in a null `version`, which is metadata and not
part of the spec.

#### Scenario: Changed spec never rewrites an existing row
- **WHEN** a catalog file's template spec changes
- **THEN** the previously canonical template row SHALL keep its spec fields
  unchanged and stay non-deleted

#### Scenario: Deployments retain their applied template
- **WHEN** a new canonical template is inserted for a product
- **THEN** existing deployments' `applied_template_id` values SHALL be
  unchanged and SHALL still resolve to their original template rows

#### Scenario: A set version is never overwritten
- **WHEN** a template row already has a non-null `version`
- **THEN** the reconciler SHALL leave that `version` unchanged

### Requirement: The reconciler never writes visibility after product creation
The reconciler SHALL treat `visibility` as runtime state owned by the database,
not by the catalog. It MAY initialize `visibility` when it creates a product,
and MUST NOT write the field on any subsequent run, so that an administrator's
change to a curated product's visibility is never reverted by a rollout. A
product the reconciler creates SHALL start hidden, so that merging a catalog
change can never by itself expose a product to end users.

#### Scenario: Newly created product starts hidden
- **WHEN** the reconciler creates a product from a catalog file
- **THEN** that product's `visibility` SHALL be `admin`

#### Scenario: Administrator's visibility change survives reconciliation
- **WHEN** an admin sets a curated product's `visibility` to `public` and the
  reconciler subsequently runs
- **THEN** that product's `visibility` SHALL remain `public`

#### Scenario: Adoption does not change visibility
- **WHEN** the reconciler adopts an existing non-curated product
- **THEN** that product's `visibility` SHALL be unchanged

### Requirement: The reconciler adopts matching non-curated products
When a catalog file's slug does not match any product, the reconciler SHALL
look for a non-curated, non-deleted product whose name matches the catalog
file's `product.name` case-insensitively, and adopt it by assigning the slug
and setting `curated` to true. If no such product exists, the reconciler SHALL
create a new product. Adoption SHALL be logged with the adopted product id.

#### Scenario: Hand-authored product is adopted
- **WHEN** a catalog file for slug `immich` is added and a non-curated product
  named `Immich` exists
- **THEN** the reconciler SHALL set that product's `slug` to `immich` and
  `curated` to true rather than creating a second product

#### Scenario: Adoption of a generated product creates no template
- **WHEN** a product's catalog file was generated by `catalog curate` and is
  then reconciled for the first time
- **THEN** the existing template SHALL match by spec equality and no new
  template row SHALL be inserted

#### Scenario: No matching product creates one
- **WHEN** a catalog file declares a slug and name that match no existing
  product
- **THEN** the reconciler SHALL create a new curated product and insert its
  template

### Requirement: The reconciler materializes product icons to static storage
The reconciler SHALL read each curated product's referenced icon file, process
it through the same pipeline used for icons uploaded via the API — orientation
normalization, center crop, downscale, and PNG encoding — derive its
content-addressed relative path from the processed bytes, ensure that file
exists in static storage, and set the product's `rel_icon_path` to it. Because
static storage is a per-environment volume while the catalog is shared across
environments, the reconciler MUST verify that the file is present on disk
rather than inferring presence from the stored path.

#### Scenario: Icon is materialized on first reconciliation
- **WHEN** a curated product's icon has not yet been written to static storage
- **THEN** the reconciler SHALL process the source image and write the
  content-addressed file
- **AND** SHALL set the product's `rel_icon_path` to that path

#### Scenario: Unchanged icon is not rewritten
- **WHEN** the product's `rel_icon_path` already matches the processed image's
  content-addressed path and that file exists in static storage
- **THEN** the reconciler SHALL leave both the file and the path unchanged

#### Scenario: Empty volume is repopulated
- **WHEN** a product's `rel_icon_path` is already correct but static storage
  does not contain that file, such as after a restore onto a fresh volume
- **THEN** the reconciler SHALL write the file

#### Scenario: Changing an icon creates no template version
- **WHEN** a curated product's icon changes and its template spec does not
- **THEN** the product's `rel_icon_path` SHALL be updated
- **AND** no new template row SHALL be inserted

#### Scenario: Unreadable icon fails the run
- **WHEN** a curated product's referenced icon file is missing or cannot be
  processed as an image
- **THEN** the reconciler SHALL fail and apply no changes from that run

### Requirement: The reconciler ignores non-curated products
Every reconciler query that selects products to act on SHALL filter on
`curated = true`. The reconciler MUST NOT modify, soft delete, or repoint any
product with `curated = false`, including when such a product has no catalog
file.

#### Scenario: Experimental products are untouched
- **WHEN** the reconciler runs while non-curated products exist that have no
  catalog file
- **THEN** those products and their templates SHALL be left unchanged

### Requirement: Removing a catalog file uncurates its product
The reconciler SHALL clear `curated` and `slug` on any product whose slug is no
longer declared by a catalog file, so that the presence of a catalog file is the
sole expression of whether a product is catalog-managed. Uncurating SHALL leave
the product's other fields, its template rows, its canonical `template_id`, its
`visibility`, and its deployments unchanged, and SHALL be logged with the
affected slug.

#### Scenario: Deleting a catalog file releases the product
- **WHEN** a product's catalog file is removed and the change is rolled out
- **THEN** that product's `curated` SHALL become false and its `slug` SHALL
  become null
- **AND** the product SHALL become editable through the REST API, CLI, and
  admin UI

#### Scenario: Uncurated product keeps its templates and deployments
- **WHEN** a product is uncurated by removal of its catalog file
- **THEN** its template rows, canonical `template_id`, `visibility`, and
  deployments SHALL be unchanged

#### Scenario: Restoring the file re-adopts the product
- **WHEN** a removed catalog file is restored and rolled out
- **THEN** the reconciler SHALL adopt the product again by name and set
  `curated` to true

### Requirement: An unreadable catalog directory aborts the run
The reconciler SHALL raise an error and apply no changes when the configured
catalog directory does not exist or cannot be read, rather than proceeding as
though it declared no products. Failing to read the desired state is not the
same as the desired state being empty, and treating it as such would uncurate
every product at once.

An empty catalog directory is valid desired state, meaning no product is
catalog-managed. It occurs legitimately before any product has been curated and
on environments that curate nothing, and SHALL be reconciled normally.

#### Scenario: Missing catalog directory aborts
- **WHEN** the configured catalog directory does not exist
- **THEN** the reconciler SHALL fail and apply no changes

#### Scenario: Empty catalog directory is valid
- **WHEN** the configured catalog directory exists and contains no catalog
  documents
- **THEN** the reconciler SHALL complete successfully
- **AND** SHALL uncurate any product that is still curated

### Requirement: The reconciler applies the catalog during rollout
The catalog SHALL be baked into the API container image, and reconciliation
SHALL run from an init container that executes after the existing database
migration init container. The reconciler MUST NOT require runtime access to a
git remote or require cluster credentials to be held by CI. A reconciliation
failure SHALL fail the init container so that new pods do not become ready and
the previously running version continues serving.

The image build SHALL NOT use path filters that exclude catalog files: a
commit touching only `products/catalog/` must still produce an image, or the
merged change would never roll out.

#### Scenario: Catalog applies on rollout
- **WHEN** a commit changing only catalog files is merged and the resulting
  image is rolled out
- **THEN** the init container SHALL apply the catalog before the API container
  starts

#### Scenario: Invalid catalog blocks the rollout
- **WHEN** the baked catalog fails validation
- **THEN** the init container SHALL exit non-zero
- **AND** the previously running pods SHALL continue serving the prior catalog

### Requirement: Concurrent reconciliation is serialized
Catalog application SHALL acquire a database-level advisory lock for the
duration of the transaction, so that concurrent init containers across multiple
replicas cannot both observe a missing template and insert duplicates.

#### Scenario: Two replicas start simultaneously
- **WHEN** two pods run the catalog init container at the same time against the
  same database
- **THEN** exactly one SHALL apply changes while the other waits
- **AND** the final state SHALL contain no duplicate template rows

### Requirement: Inserted templates record their originating commit
When the reconciler inserts a template row it SHALL set `catalog_commit` to the
git commit identifier of the catalog that produced it, read from the
`GIT_COMMIT` environment variable present in the image. This value is recorded
for audit purposes and SHALL NOT be read by application logic or affect
matching.

#### Scenario: Insert records the commit
- **WHEN** the reconciler inserts a template while `GIT_COMMIT` is `75eccfc`
- **THEN** the new row's `catalog_commit` SHALL be `75eccfc`

#### Scenario: Reused templates are not stamped
- **WHEN** the reconciler matches an existing template rather than inserting
- **THEN** that row's `catalog_commit` SHALL be left unchanged

### Requirement: The reconciler applies listing fields in place
On every run the reconciler SHALL write each curated product's `tagline`,
`description`, `license`, `features` and `links` from its catalog document onto
the product row, replacing the previous values. Changing these fields SHALL NOT
insert a template row.

#### Scenario: Changed tagline
- **WHEN** a catalog document's `tagline` changes and its template spec does
  not
- **THEN** the product's `tagline` is updated and no template row is inserted

#### Scenario: Removed feature
- **WHEN** a feature is deleted from a catalog document
- **THEN** the product's `features` no longer contain it after the next run

### Requirement: The reconciler materializes screenshots to static storage
The reconciler SHALL process each declared screenshot into two web images, a
thumbnail sized for in-page display and a full-size rendition, store both in
static storage under content-addressed paths, verify the files are on disk,
and set the product's `screenshots` to the declared entries in order, each
pointing at its stored files.

#### Scenario: First run writes screenshots
- **WHEN** a curated product declares two screenshots that are not yet in
  static storage
- **THEN** the reconciler writes a thumbnail and a full-size file for each,
  and the product lists both screenshots in declared order

#### Scenario: Empty volume is repopulated
- **WHEN** a product's screenshot entries are already correct but static
  storage lacks a referenced thumbnail or full-size file
- **THEN** the reconciler writes that file again

#### Scenario: Unreadable screenshot fails the run
- **WHEN** a declared screenshot cannot be processed as an image
- **THEN** the reconciler fails and applies no changes from that run

### Requirement: The reconciler stamps template versions
When the reconciler inserts a template row it SHALL set `version` from the
document's `upstream` block. On every run it SHALL also fill in the null
`version` of each existing template row of a curated product when the current
`upstream.version_path` resolves on that row and its value matches
`upstream.match`.

#### Scenario: Inserted template is stamped
- **WHEN** the reconciler inserts a template for a document pinning image tag
  `v3.3.1` with match `^v(?P<version>.+)$`
- **THEN** the new row's `version` is `3.3.1`

#### Scenario: Existing rows are backfilled
- **WHEN** a curated product has older template rows with null versions whose
  image tags match the current `upstream.match`
- **THEN** after the run those rows carry their derived versions

#### Scenario: Placeholder upstream stamps nothing
- **WHEN** a curated product's value at `version_path` does not match
  `upstream.match`
- **THEN** its template rows keep a null `version`

### Requirement: The reconciler keeps releases in sync with the releases file
On every run the reconciler SHALL make a curated product's `product_release`
rows equal its `releases.yaml`: insert new versions, update changed notes or
positions, and delete versions the file no longer lists. A product without a
releases file SHALL end the run with no release rows.

#### Scenario: New release appended by an upgrade
- **WHEN** a merged upgrade adds version `3.4.0` to the top of
  `releases.yaml`
- **THEN** after the next run the product has a `3.4.0` release listed first

#### Scenario: Corrected notes
- **WHEN** the notes of an existing version are edited in `releases.yaml`
- **THEN** that release's notes are updated and no duplicate row exists

#### Scenario: Version removed from the file
- **WHEN** a version is deleted from `releases.yaml`
- **THEN** its release row is deleted on the next run

### Requirement: Releasing a product leaves its listing data alone
When the reconciler uncurates a product because its catalog folder was
removed, it SHALL leave the product's listing fields, screenshots and release
rows unchanged, like its templates.

#### Scenario: Catalog folder removed
- **WHEN** a curated product's catalog folder is deleted and the catalog is
  applied
- **THEN** the product is uncurated and keeps its tagline, screenshots and
  releases
