## ADDED Requirements

### Requirement: Each catalog app's page has its own HTML
The UI build SHALL emit, for every product folder in `products/catalog`
other than `custom`, an HTML page for `/apps/<slug>` identical to the built
`index.html` except for its title, description and link-preview tags.

#### Scenario: Developer product
- **WHEN** the UI is built
- **THEN** no page is emitted for `custom`, which `/dev` already covers

### Requirement: The preview tags describe the app
An app page's title and `og:title` SHALL be `<name> on Freepod`, its
`og:description` the product's tagline, its `description` meta tag the first
paragraph of the product's description, and its `og:url` the page's URL. A
product without a tagline SHALL fall back to a generic line naming it.

#### Scenario: Shared link to an app page
- **WHEN** a link crawler fetches `/apps/immich`
- **THEN** the response carries `og:title` "Immich on Freepod", Immich's
  tagline as `og:description`, and Immich's card as `og:image`

#### Scenario: Catalog change
- **WHEN** a product's tagline changes in its catalog file and the UI image is
  rebuilt
- **THEN** its page's preview shows the new tagline without a UI code change

### Requirement: Each catalog app has a card image
The build SHALL render a 1200x630 PNG card per app showing its icon, name,
category, tagline and the services it replaces, each omitted when absent,
with the Freepod mark, and SHALL emit it under a content-hashed file name.

#### Scenario: Card is immutable-cacheable
- **WHEN** a product's card changes
- **THEN** it is served from a new URL

### Requirement: nginx serves the app pages
nginx SHALL serve an app's page for `/apps/<slug>` and `/apps/<slug>/`, and
SHALL serve `index.html` for a slug with no page, so the SPA still renders
it.

#### Scenario: App without a catalog folder
- **WHEN** a visitor opens `/apps/<slug>` for a product that exists only in
  the database
- **THEN** the SPA renders the page with the generic preview tags
