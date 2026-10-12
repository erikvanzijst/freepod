## MODIFIED Requirements

### Requirement: Products carry a visibility setting
The `product` table SHALL carry a non-null `visibility` column accepting the
values `public`, `unlisted` and `admin`. `public` means the product is offered
to end users in the product catalog and the storefront; `unlisted` means it is
offered to end users through the API and the client but not shown in the
storefront; `admin` means it is hidden from end users. Visibility SHALL be
independent of the `curated` flag, so that a product may be catalog-managed
yet hidden or unlisted, or database-authored yet public.

#### Scenario: Curated and hidden
- **WHEN** a curated product declares `visibility: admin`
- **THEN** it SHALL remain reconciler-managed while being hidden from end users

#### Scenario: Deprecated product stays manageable
- **WHEN** a curated product is superseded and its visibility is set to `admin`
- **THEN** it SHALL continue to receive catalog updates without being offered
  to new users

#### Scenario: Curated and unlisted
- **WHEN** a curated product's visibility is set to `unlisted`
- **THEN** it SHALL remain reconciler-managed while being kept out of the
  storefront

### Requirement: End-user product listings filter on visibility
Product listings served to end users SHALL include only non-deleted products
whose `visibility` is `public` or `unlisted`. Products with `visibility` of
`admin` SHALL NOT appear in end-user listings regardless of their `curated`
value. The listing SHALL report each product's `visibility` to every caller,
including anonymous ones, so that a client can tell `public` from `unlisted`.

#### Scenario: Hidden product is excluded
- **WHEN** an end user requests the product list and a product has
  `visibility: admin`
- **THEN** that product SHALL NOT appear in the response

#### Scenario: Public products are listed
- **WHEN** an end user requests the product list
- **THEN** every non-deleted product with `visibility: public` SHALL appear,
  whether curated or not

#### Scenario: Unlisted products are listed with their visibility
- **WHEN** an anonymous visitor or a non-admin user requests the product list
  and a product has `visibility: unlisted`
- **THEN** that product SHALL appear in the response
- **AND** its `visibility` SHALL be reported as `unlisted`

### Requirement: Administrators can change the visibility of any product
Administrators SHALL be able to change any product's `visibility` through the
REST API, the CLI, and the admin UI, whether the product is curated or not, so
that a product can be published, unlisted or withdrawn immediately rather than
waiting for a merge and a rollout. The curated write guard SHALL NOT block a
visibility change: the catalog owns what a product is, while the database owns
whether it is currently offered. The admin UI SHALL present visibility as an
explicit control in the product detail panel offering all three values, showing
the product's current setting with a description of where a product with that
setting appears, and SHALL remain enabled for curated products even where the
rest of the panel is read-only.

#### Scenario: Admin publishes a product
- **WHEN** an admin changes a product's visibility from `admin` to `public`
- **THEN** the change SHALL be persisted
- **AND** the product SHALL subsequently appear in the end-user product list

#### Scenario: Admin withdraws a product
- **WHEN** an admin changes a product's visibility from `public` to `admin`
- **THEN** the product SHALL no longer appear in the end-user product list
- **AND** existing deployments of that product SHALL be unaffected

#### Scenario: Admin unlists a product
- **WHEN** an admin changes a product's visibility to `unlisted`
- **THEN** the product SHALL remain in the end-user product list
- **AND** it SHALL no longer appear in the storefront

#### Scenario: Admin UI describes unlisted
- **WHEN** an admin views the visibility control of an unlisted product
- **THEN** the control SHALL show `Unlisted` and state that the product is
  available through the API and CLI but hidden from the storefront

#### Scenario: Curated product visibility remains editable
- **WHEN** an admin changes a curated product's visibility
- **THEN** the change SHALL be applied without requiring the force option
- **AND** the control SHALL be enabled in the admin UI

#### Scenario: CLI changes visibility at parity with the API
- **WHEN** an admin runs `update-product` with a visibility option, including
  `unlisted`
- **THEN** the value SHALL be updated exactly as it is through the REST API

#### Scenario: Visibility changes are recorded
- **WHEN** a product's visibility changes
- **THEN** the event SHALL be logged with the acting user and the product

## ADDED Requirements

### Requirement: The storefront shows only public products
The public marketing site (the landing page showcase, the hero constellation
and the pricing section) SHALL show only products whose `visibility` is
`public`, deciding from the `visibility` the product listing reports. It SHALL
NOT select or exclude products by name.

#### Scenario: Unlisted product is kept out of the storefront
- **WHEN** the product listing contains an `unlisted` product
- **THEN** the showcase, hero constellation and pricing section SHALL NOT show
  it, nor a category that only unlisted products carry

#### Scenario: Public product appears regardless of its name
- **WHEN** a `public` product is named like a demo product, such as
  "Hello World"
- **THEN** the storefront SHALL show it

### Requirement: Unlisted products are deployable like public ones
A product whose `visibility` is `unlisted` SHALL be readable by id, and its
templates and plans SHALL resolve, and a deployment of it SHALL be created,
exactly as for a `public` product.

#### Scenario: End user deploys an unlisted product
- **WHEN** a non-admin user creates a deployment of an `unlisted` product's
  canonical template on one of its plans
- **THEN** the deployment SHALL be created as it would be for a `public`
  product

#### Scenario: Unlisted product's plans are readable anonymously
- **WHEN** an anonymous visitor reads an `unlisted` product's plans
- **THEN** they SHALL be returned as for a `public` product

### Requirement: Adding the unlisted value changes no existing product
The migration that introduces `unlisted` SHALL add it to the stored set of
visibility values without changing any product's `visibility`, and new
products SHALL still default to `admin`. Its downgrade SHALL set every
`unlisted` product to `public`, so that those products stay reachable through
the API, before removing the value.

#### Scenario: Upgrade leaves existing rows alone
- **WHEN** the migration is applied to a database with `public` and `admin`
  products
- **THEN** every product SHALL keep its previous `visibility`
- **AND** a product SHALL then be accepted with `visibility: unlisted`

#### Scenario: Downgrade makes unlisted products public
- **WHEN** the migration is downgraded while a product is `unlisted`
- **THEN** that product's `visibility` SHALL be `public`
