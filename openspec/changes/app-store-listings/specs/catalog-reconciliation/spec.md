## MODIFIED Requirements

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

## ADDED Requirements

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
