## MODIFIED Requirements

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
