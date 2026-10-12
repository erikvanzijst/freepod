## Purpose

Store the store-listing content of a product (tagline, license, feature
bullets, outbound links and screenshots) on the product itself, and expose it
through the API and CLI so the public app pages render it without hard-coded
UI content.

## ADDED Requirements

### Requirement: Products store listing fields
A product SHALL store these optional listing fields: `tagline` (one sentence of
text), `license` (an SPDX-style license name), `features`, `links`, and
`screenshots`. The list fields SHALL default to empty lists and the text fields
to null, so a product with none of them is valid. A product's `description`
SHALL be its long description, written as Markdown.

#### Scenario: Product without listing fields
- **WHEN** a product is created without any listing fields
- **THEN** it is valid, its `tagline` and `license` are null, and its
  `features`, `links` and `screenshots` are empty lists

#### Scenario: Listing fields are persisted
- **WHEN** a product is saved with a `tagline`, a `license`, two features and
  three links
- **THEN** a later read of that product returns the same values in the same
  order

### Requirement: Features have a title, a body and an icon key
Each entry in `features` SHALL have a non-empty `title`, a non-empty `body`,
and an `icon` key naming one icon from a fixed set the UI understands. An
unrecognized icon key SHALL NOT be rejected by the API; the UI SHALL render a
generic icon for it.

#### Scenario: Feature with a known icon
- **WHEN** a product declares a feature with `icon: sync`
- **THEN** the API returns that feature with `icon` equal to `sync`

#### Scenario: Feature with an unknown icon
- **WHEN** a product declares a feature whose `icon` is not in the UI's set
- **THEN** the product is accepted and the page renders that feature with a
  generic icon

### Requirement: Links have a label, an HTTPS URL and a kind
Each entry in `links` SHALL have a non-empty `label`, an absolute `https://`
URL in `href`, and a `kind` from `website`, `docs`, `source`, `releases`, `ios` and
`android`. A link with any other kind or a non-HTTPS URL SHALL be rejected.

#### Scenario: Valid link
- **WHEN** a product declares a link with kind `ios` and an `https://` URL
- **THEN** the link is stored and returned unchanged

#### Scenario: Insecure link is rejected
- **WHEN** a product declares a link whose URL starts with `http://`
- **THEN** the write is rejected with a validation error naming the link

#### Scenario: Unknown link kind is rejected
- **WHEN** a product declares a link with kind `blog`
- **THEN** the write is rejected with a validation error naming the kind

### Requirement: Screenshots carry a caption, a form and an optional credit
Each entry in `screenshots` SHALL have a `thumbnail_url` (a small rendition
for in-page display), a `url` (the full-size rendition), a non-empty
`caption`, a `form` of `desktop` or `mobile`, and an optional `credit` with a
non-empty `text` and an optional `https://` `href`. Screenshots SHALL be
returned in their declared order.

#### Scenario: Screenshot with a credit
- **WHEN** a product's screenshot declares a credit with text and href
- **THEN** the listing returns the screenshot with that credit and both URLs

#### Scenario: Screenshot without a credit
- **WHEN** a product's screenshot declares no credit
- **THEN** the listing returns the screenshot with a null `credit`

### Requirement: Screenshots are set only through the catalog
Screenshots SHALL be written only by the catalog reconciler. The product create
and update APIs and CLI commands SHALL NOT accept `screenshots`, so a product
that is not in the catalog has no screenshots.

#### Scenario: API write with screenshots is rejected
- **WHEN** an admin sends `screenshots` in a product create or update request
- **THEN** the request is rejected as an unknown field

### Requirement: A migration adds the listing columns
An Alembic migration SHALL add `tagline`, `license`, `features`, `links` and
`screenshots` to the `product` table, keep every existing row valid with null
text fields and empty lists, and provide a downgrade that removes the columns.

#### Scenario: Upgrade preserves existing products
- **WHEN** the migration runs on a database with existing products
- **THEN** every product keeps its other fields, with null `tagline` and
  `license` and empty `features`, `links` and `screenshots`

#### Scenario: Downgrade removes the columns
- **WHEN** the migration is downgraded
- **THEN** the five listing columns no longer exist on `product`

### Requirement: Product reads carry the tagline but not the listing content
Every product read SHALL include `tagline`. Product reads SHALL NOT include
`license`, `features`, `links` or `screenshots`; those are served only by the
product's listing endpoint, so responses that list or nest products stay small.

#### Scenario: Product list stays lean
- **WHEN** a client lists products
- **THEN** each product includes its `tagline` and none of `features`,
  `links`, `screenshots` or `license`

### Requirement: A listing endpoint serves a product's full listing content
`GET /api/products/{product_id}/listing` SHALL return the product's `license`,
`features`, `links` and `screenshots`, together with the product version
fields defined by the `product-releases` capability. It SHALL be readable by
the same callers as the product, including anonymous visitors.

#### Scenario: Anonymous visitor reads a listing
- **WHEN** an anonymous client requests the listing of a public product
- **THEN** it receives the license, features, links and screenshots in their
  declared order

#### Scenario: Product without listing content
- **WHEN** the listing of a product with no listing fields is requested
- **THEN** the response has a null `license` and empty `features`, `links`
  and `screenshots`

#### Scenario: Unknown product
- **WHEN** the listing of a product that does not exist is requested
- **THEN** the endpoint responds with not found

### Requirement: Nested products use a summary shape
Wherever a product appears nested inside another resource, such as a template
or a deployment's template, it SHALL be a summary with only `id`, `name`,
`slug`, `icon_url`, `tagline` and `template_id`. Clients that need more SHALL
read the product itself.

#### Scenario: Deployment response
- **WHEN** a client lists its deployments
- **THEN** each deployment's template carries a product summary without
  `description`, `category`, `replaces` or listing content

### Requirement: Content-addressed static images are cached immutably
Static files served under content-addressed paths, such as icons and
screenshot renditions, SHALL be sent with a `Cache-Control` header that lets
browsers and proxies keep them for at least a year without revalidation.

#### Scenario: Screenshot response headers
- **WHEN** a browser downloads a screenshot rendition
- **THEN** the response carries `Cache-Control` with `immutable` and a
  `max-age` of at least one year

### Requirement: Admins write listing text fields of non-curated products
Product create and update SHALL accept `tagline`, `license`, `features` and
`links`, with update changing only the fields it is given. For a curated
product these writes SHALL be rejected by the existing curated-product write
guard, because the catalog file owns them.

#### Scenario: Update one listing field
- **WHEN** an admin updates only the `tagline` of a non-curated product
- **THEN** the `tagline` changes and the other listing fields are unchanged

#### Scenario: Curated product rejects listing writes
- **WHEN** an admin updates the `features` of a curated product
- **THEN** the request is rejected with a validation error naming the
  product's catalog file

### Requirement: The CLI writes listing fields at parity with the API
The `create-product` and `update-product` commands SHALL set `tagline` and
`license` through options, and `features` and `links` from a JSON or YAML file,
with the same validation and curated-product rules as the API. A
`get-product-listing` command SHALL print a product's listing in the same
shape as the listing endpoint.

#### Scenario: CLI sets features from a file
- **WHEN** an admin runs `update-product` with a features file for a
  non-curated product
- **THEN** the product's `features` equal the file's entries

#### Scenario: CLI prints a listing
- **WHEN** an operator runs `get-product-listing` for a product
- **THEN** the command prints the same fields as the listing endpoint, as YAML

### Requirement: The admin product form edits listing text
The admin product form SHALL let administrators edit `tagline` and `license`
of a non-curated product and edit `description` as multi-line text. For a
curated product these inputs SHALL be read-only and SHALL name the product's
catalog file.

#### Scenario: Curated listing text is read-only
- **WHEN** an admin opens a curated product in the admin UI
- **THEN** the tagline, license and description inputs are read-only and the
  catalog file is named
