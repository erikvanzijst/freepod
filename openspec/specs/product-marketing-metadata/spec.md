# product-marketing-metadata Specification

## Purpose


Store per-product marketing copy (`category` and `replaces`) on the product so
it is served by the API and editable via the REST API, CLI, and admin UI,
instead of being hardcoded in the frontend. The anonymous landing page renders
this metadata from the API — sourcing the one-sentence blurb from the product's
existing `description` — and the hero constellation lists the distinct product
categories rather than product names.

## Requirements


### Requirement: Product model stores marketing metadata
The product model (`ProductORM`) SHALL store the following nullable marketing
metadata fields, each persisted as a nullable text column on the `product`
table:

- `category`: the product's category (e.g. "Photos & video", "Messaging",
  "Passwords & passkeys").
- `replaces`: the proprietary services the product replaces (e.g.
  "Google Photos · iCloud Photos", "Slack · Microsoft Teams").

Both fields SHALL be optional; a product with neither set is valid.
Purely presentational tokens (such as a per-product accent color) are NOT
product data and SHALL NOT be stored on the model. The former `engine` note (a
brand-vs-software label) is NOT modeled and SHALL NOT be stored on the product.
The one-sentence blurb is the product's `tagline`, a listing field defined by
the `product-listing-metadata` capability; `description` holds the long
description.

#### Scenario: Product persists marketing metadata
- **WHEN** a product is created or updated with `category` and `replaces`
  values
- **THEN** those values are persisted on the `product` row and returned on
  subsequent reads of that product

#### Scenario: Marketing metadata is optional
- **WHEN** a product is created without any marketing metadata
- **THEN** the product is created successfully and its `category` and
  `replaces` fields are null

### Requirement: Database migration adds marketing metadata columns
An Alembic migration SHALL add the two nullable text columns (`category`,
`replaces`) to the `product` table, and SHALL provide a
downgrade that removes them. Existing product rows SHALL remain valid after the
migration with the new columns set to null.

#### Scenario: Upgrade adds columns to existing data
- **WHEN** the migration is applied to a database containing existing products
- **THEN** the two new columns exist on the `product` table
- **AND** existing product rows are preserved with the new columns null

#### Scenario: Downgrade removes the columns
- **WHEN** the migration is downgraded
- **THEN** the two marketing-metadata columns are removed from the `product`
  table

### Requirement: API exposes and accepts marketing metadata
The product API SHALL return the marketing metadata fields on the product read
schema (`ProductRead`) and SHALL accept them on the product create and update
schemas (`ProductCreate` / `ProductUpdate`). Update SHALL allow setting any
subset of the fields without disturbing the others, consistent with the
existing partial-update behavior for product fields. For curated products,
update SHALL be rejected by the service-layer write guard, because `category`
and `replaces` are sourced from the product's catalog file.

#### Scenario: Read returns marketing metadata
- **WHEN** a client fetches a product (`GET /api/products/{id}` or
  `GET /api/products`)
- **THEN** the response includes the product's `category` and `replaces` fields

#### Scenario: Create accepts marketing metadata
- **WHEN** an admin creates a product with marketing metadata in the payload
- **THEN** the created product is returned with those fields populated

#### Scenario: Update changes a subset of fields
- **WHEN** an admin updates a non-curated product, providing only `category`
- **THEN** the product's `category` is updated
- **AND** its other marketing-metadata fields are unchanged

#### Scenario: Update of a curated product is rejected
- **WHEN** an admin updates a curated product's `category` or `replaces`
- **THEN** the request SHALL be rejected with a validation error naming the
  product's catalog file

### Requirement: CLI manages marketing metadata at parity with the API
The CLI SHALL be able to set the marketing metadata fields when creating a
product and when updating a product, providing the same capability as the REST
API so the two remain in lockstep.

#### Scenario: CLI creates a product with marketing metadata
- **WHEN** an admin runs the `create-product` command with options for
  `category` and `replaces`
- **THEN** the created product carries those values

#### Scenario: CLI updates marketing metadata
- **WHEN** an admin runs the `update-product` command with one or more
  marketing-metadata options
- **THEN** the specified fields are updated and the others are left unchanged

### Requirement: Admin UI edits marketing metadata
The admin product create and edit experience SHALL allow entering and editing
the `category` and `replaces` fields for non-curated products, so
administrators can manage product marketing copy without changing frontend
code. For curated products these inputs SHALL be read-only, and the catalog
file SHALL be identified as the place to change them.

#### Scenario: Admin sets marketing metadata when creating a product
- **WHEN** an admin fills in the marketing-metadata inputs while creating a
  product
- **THEN** the values are submitted to the API and saved on the product

#### Scenario: Admin edits marketing metadata on an existing product
- **WHEN** an admin edits the marketing-metadata inputs on an existing
  non-curated product
- **THEN** the changes are persisted via the product update API

#### Scenario: Curated product metadata is read-only
- **WHEN** an admin views the marketing-metadata inputs of a curated product
- **THEN** the inputs SHALL be read-only and SHALL name the product's catalog
  file

### Requirement: Landing page renders marketing metadata from the API
The anonymous landing page SHALL render each product's `category` and
`replaces` from the product API instead of the hardcoded `APPS`
map in `landingTokens.ts`, and SHALL render the one-sentence blurb from the
product's `tagline` field. When a field is empty, the landing page SHALL
gracefully omit the corresponding element rather than render a placeholder or
break; in particular it SHALL NOT fall back to the long `description`. The
hardcoded marketing content for these fields SHALL be removed once the page
reads them from the API; non-product presentational tokens (such as accent
color) MAY remain in the UI. The former `engine` note SHALL no longer be
rendered: its `AppEntry` field and its card rendering SHALL be removed. Each
product card SHALL link to that product's `/apps/:slug` page.

The hero "constellation" SHALL list the distinct product categories (deduplicated,
in first-seen order) rather than product names, since the apps and pricing
sections already list products. Each category MAY be shown with a generic
category icon; category labels are sufficiently static that a small
icon-by-category map MAY live in the UI, with a generic fallback icon for an
unrecognized category.

#### Scenario: Landing page shows API-provided metadata
- **WHEN** the landing page renders a product whose API record has
  `category`, `replaces`, and a `tagline`
- **THEN** the page displays the category, the replaces line, and the
  tagline as the blurb for that product

#### Scenario: Graceful fallback for empty fields
- **WHEN** the landing page renders a product whose `category`, `tagline` (or
  any other marketing field) is empty
- **THEN** the page omits that element and renders the rest of the product
  without error

#### Scenario: Long description is not used as a blurb
- **WHEN** a product has a `description` but no `tagline`
- **THEN** its landing card shows no blurb

#### Scenario: Card links to the app page
- **WHEN** a visitor selects the Immich card on the landing page
- **THEN** they are taken to `/apps/immich`

#### Scenario: Engine note is no longer rendered
- **WHEN** the landing page renders any product
- **THEN** no brand-vs-software `engine` note is shown on the card

#### Scenario: Hero constellation lists categories
- **WHEN** the hero section renders and the visible products carry `category`
  values
- **THEN** the constellation shows each distinct category once (not product
  names), with a generic icon per category and a fallback icon for an
  unrecognized category
