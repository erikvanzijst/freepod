## MODIFIED Requirements

### Requirement: The storefront shows only public products
The public marketing site (the landing page showcase, the hero constellation,
the pricing section and the app catalog) SHALL show only products whose
`visibility` is `public`, deciding from the `visibility` the product listing
reports. It SHALL NOT select or exclude products by name. For an
administrator, the app catalog, both at `/apps` and in the dashboard's
add-an-app panel, SHALL also list `unlisted` and `admin` products, after the
`public` ones and each marked with its visibility; the rest of the storefront
SHALL show administrators what it shows everyone else.

#### Scenario: Unlisted product is kept out of the storefront
- **WHEN** the product listing contains an `unlisted` product and the visitor
  is not an administrator
- **THEN** the showcase, hero constellation, pricing section and app catalog
  SHALL NOT show it, nor a category that only unlisted products carry

#### Scenario: Public product appears regardless of its name
- **WHEN** a `public` product is named like a demo product, such as
  "Hello World"
- **THEN** the storefront SHALL show it

#### Scenario: Administrator sees non-public products in the catalog
- **WHEN** an administrator opens `/apps` and products exist with each
  visibility
- **THEN** the `public` products are listed first, followed by the `unlisted`
  and `admin` ones
- **AND** each non-public product is marked as unlisted or admin-only

#### Scenario: Administrator's landing page is unchanged
- **WHEN** an administrator opens the landing page
- **THEN** its showcase shows only `public` products
