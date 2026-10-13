# product-catalog-format Specification

## Purpose


Defines the `products/catalog/<slug>.yaml` file contract: the required
`product`, `upstream`, and `template` blocks, how icons are referenced, and
the validation rules that a catalog file must satisfy before it is applied.

## Requirements


### Requirement: Published products are declared as catalog files
The repository SHALL contain a top-level `products/catalog/` directory holding
one folder per published product, `products/catalog/<slug>/`, and each folder
SHALL contain that product's catalog document named `<slug>.yaml`. The
`product.slug` value inside a document MUST equal its folder name and its
filename stem, and slugs MUST be unique across the catalog. A product's
catalog folder is the authoritative declaration of that product's marketing and
listing metadata, icon, screenshots, release notes, chart reference, system
values, and user values schema.

#### Scenario: Catalog file declares a product
- **WHEN** `products/catalog/immich/immich.yaml` exists with
  `product.slug: immich`
- **THEN** it SHALL be the authoritative declaration for the Immich product

#### Scenario: Slug does not match filename
- **WHEN** `products/catalog/immich/immich.yaml` declares
  `product.slug: photos`
- **THEN** validation SHALL fail with an error identifying the mismatched file

#### Scenario: Folder without a document
- **WHEN** `products/catalog/immich/` exists but contains no `immich.yaml`
- **THEN** validation SHALL fail with an error naming the folder

#### Scenario: Top-level document from the old layout
- **WHEN** a document exists directly at `products/catalog/immich.yaml`
- **THEN** validation SHALL fail with an error naming the file and the
  expected per-product folder

#### Scenario: Duplicate slugs across files
- **WHEN** two catalog files declare the same `product.slug`
- **THEN** validation SHALL fail and identify both files

### Requirement: Catalog files carry a schema version
Each catalog file SHALL declare a top-level `schema_version` integer. The
reconciler MUST reject a file whose `schema_version` it does not recognize,
rather than applying a partially understood document.

#### Scenario: Recognized schema version
- **WHEN** a catalog file declares `schema_version: 1` and the reconciler
  supports version 1
- **THEN** the file SHALL be accepted for processing

#### Scenario: Unrecognized schema version
- **WHEN** a catalog file declares a `schema_version` the reconciler does not
  support
- **THEN** the reconciler SHALL reject the file with an error naming the file
  and the unsupported version

### Requirement: The product block declares catalog-managed product fields
Each catalog file SHALL contain a `product` block declaring `slug` and `name`,
and MAY declare `tagline`, `description` (Markdown), `category`, `replaces`,
`icon`, `license`, `features`, `links` and `screenshots`. These values are
applied to the corresponding `product` row fields on every reconciliation, and
a field the block omits is applied as null or as an empty list.

The block SHALL NOT declare `visibility`. Whether a product is offered to end
users is runtime state owned by the database and changed by administrators
directly, not part of the product's catalog definition.

#### Scenario: Product block is applied
- **WHEN** a catalog file declares `product.name: Immich` and
  `product.category: Photos & video`
- **THEN** the reconciled product row SHALL carry those values

#### Scenario: Listing fields are validated without a database
- **WHEN** a catalog file declares a link with an `http://` URL or a feature
  without a title
- **THEN** `catalog lint` SHALL fail and name the file and the field

#### Scenario: Declaring visibility is rejected
- **WHEN** a catalog file declares `product.visibility`
- **THEN** validation SHALL fail, because visibility is not a catalog-managed
  field

### Requirement: Icons are committed as image files inside the catalog directory
The `product.icon` value SHALL be a path to an image file, relative to the
product's catalog folder, and that file MUST live inside that folder so that
each product folder remains a self-contained unit for `apply`, `lint`, image
builds and the upgrader. Image data MUST NOT be embedded in the catalog
document, so that icon changes are reviewable as image diffs rather than as
opaque encoded text. The `icon` value MAY be omitted, in which case the product
has no icon.

#### Scenario: Icon is referenced by path
- **WHEN** `products/catalog/immich/immich.yaml` declares `product.icon:
  icon.png`
- **THEN** the image SHALL be read from `products/catalog/immich/icon.png`

#### Scenario: Embedded image data is rejected
- **WHEN** a catalog file supplies image bytes inline instead of a path
- **THEN** validation SHALL fail

#### Scenario: Icon path escaping the catalog directory is rejected
- **WHEN** a catalog file declares an `icon` path that resolves outside its
  product's catalog folder, including into another product's folder
- **THEN** validation SHALL fail

#### Scenario: Product without an icon
- **WHEN** a catalog file omits `product.icon`
- **THEN** the file SHALL be valid and the reconciled product SHALL have no
  icon

### Requirement: The template block declares the deployable spec
Each catalog file SHALL contain a `template` block declaring exactly the fields
that constitute a template version: `chart_ref`, `chart_version`,
`chart_digest`, `system_values`, and `values_schema`. The `system_values` and
`values_schema` values SHALL be written to the template row verbatim, with no
templating or substitution, so that the file content is exactly what is applied
at deploy time. The pinned application image tag lives inside `system_values`.

#### Scenario: Template block maps to a template row
- **WHEN** a catalog file declares `template.chart_ref`,
  `template.chart_version`, and `template.system_values`
- **THEN** a reconciled template row SHALL carry those values in
  `chart_ref`, `chart_version`, and `system_values_json` respectively

#### Scenario: System values are applied verbatim
- **WHEN** `template.system_values` declares `image.tag: v3.0.3`
- **THEN** the template row's `system_values_json` SHALL contain
  `{"image": {"tag": "v3.0.3"}}` with no substitution applied

### Requirement: The upstream block declares release-detection metadata
Each catalog file SHALL contain an `upstream` block declaring `source`,
`match`, and `version_path`. `source` identifies where upstream releases are
published and MUST declare a `type` (such as `github-release` or
`docker-tag`) with its type-specific locator. `match` is a regular expression
selecting eligible upstream tags and MUST define a named capture group
`version` used to order candidates. `version_path` is a dotted path into the
catalog document identifying where the winning tag is written. The `upstream`
block is consumed only by release-detection tooling and SHALL NOT be applied to
the cluster or persisted on the template row.

#### Scenario: Upstream metadata selects and orders candidates
- **WHEN** `upstream.match` is `^v(?P<version>\d+\.\d+\.\d+)$` and upstream
  publishes tags `v3.0.3`, `v3.1.0`, and `v3.1.0-beta.1`
- **THEN** only `v3.0.3` and `v3.1.0` SHALL be eligible candidates
- **AND** `v3.1.0` SHALL be ordered ahead of `v3.0.3` by its `version` group

#### Scenario: Winning tag is written verbatim to version_path
- **WHEN** `upstream.version_path` is `system_values.image.tag` and the winning
  upstream tag is `33.0.7-apache`
- **THEN** release-detection tooling SHALL write `33.0.7-apache` verbatim to
  `template.system_values.image.tag`

#### Scenario: Upstream block is not persisted
- **WHEN** a catalog file containing an `upstream` block is reconciled
- **THEN** no part of the `upstream` block SHALL appear on the resulting
  template row

### Requirement: A catalog value schema may declare var routing
A catalog file's `template.values_schema` MAY carry the routing markers defined in
`deployment-vars-schema-routing`: `x-caelus-target` and `x-caelus-sensitive` on a
top-level property, and `x-caelus-vars-additional` at the schema root.

The markers SHALL be optional, and a catalog file that carries none SHALL keep its
current meaning exactly: every property routes to the chart and the product accepts no
vars.

The catalog loader SHALL reject a file whose markers violate those rules, so that an
invalid declaration fails when the catalog is loaded rather than when a tenant later
deploys the product.

#### Scenario: A catalog file with no markers
- **WHEN** an existing catalog file is loaded unchanged
- **THEN** it is accepted
- **AND** the product accepts no vars

#### Scenario: A catalog file declaring a sensitive runtime property
- **WHEN** a catalog file marks a top-level string property as runtime and sensitive
- **THEN** it is accepted
- **AND** deployments of that product accept that var and never return its value

#### Scenario: A catalog file with an illegal marker
- **WHEN** a catalog file marks a nested property as runtime
- **THEN** loading the catalog fails with an error naming the file and the property

### Requirement: Screenshots are committed image files in the product folder
Each `product.screenshots` entry SHALL name an image `file` inside the
product's catalog folder, a `caption`, a `form` of `desktop` or `mobile`, and
an optional `credit`. Each file MUST be a PNG, JPEG or WebP image of at most
1 MB and at most 4096 px on its long edge, and a product MUST declare at most
12 screenshots totaling at most 5 MB.

#### Scenario: Screenshot is referenced by path
- **WHEN** `products/catalog/immich/immich.yaml` declares a screenshot with
  `file: screenshots/timeline.webp`
- **THEN** the image SHALL be read from
  `products/catalog/immich/screenshots/timeline.webp`

#### Scenario: Missing screenshot file
- **WHEN** a screenshot names a file that does not exist
- **THEN** validation SHALL fail and name the document and the file

#### Scenario: Oversized screenshot
- **WHEN** a screenshot file is larger than 1 MB or 4096 px on its long edge
- **THEN** validation SHALL fail and name the file and the limit

#### Scenario: Too many screenshots in total
- **WHEN** a product declares 13 screenshots, or screenshots totaling more
  than 5 MB
- **THEN** validation SHALL fail and name the document and the limit

### Requirement: Release notes live in the product folder
A product folder MAY contain `releases.yaml`: a list, newest first, of entries
with a `version` and Markdown `notes`. Versions MUST be unique within the file
and notes MUST be non-empty and within a size limit. A product without the file
has no releases.

#### Scenario: Releases file is read
- **WHEN** `products/catalog/immich/releases.yaml` lists versions `3.3.1` and
  `3.3.0`
- **THEN** the catalog declares those two releases for Immich, `3.3.1` first

#### Scenario: Duplicate version in a releases file
- **WHEN** a releases file lists the same version twice
- **THEN** validation SHALL fail and name the file and the version

#### Scenario: Product without a releases file
- **WHEN** a product folder has no `releases.yaml`
- **THEN** the folder SHALL be valid and the product SHALL have no releases
