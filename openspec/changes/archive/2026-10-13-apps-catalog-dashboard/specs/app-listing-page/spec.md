## MODIFIED Requirements

### Requirement: Each storefront product has a public page
The UI SHALL serve `/apps/:slug` to anonymous and signed-in visitors alike,
with the public site navigation and footer, for every product the product
listing returns to the visitor whose slug equals `:slug`: `public` and
`unlisted` products for everyone, and `admin` products for administrators.
Only the page of a `public` product SHALL be open to indexing by search
engines; the page of any other product, and the not-found message, SHALL ask
search engines not to index them. Any other slug SHALL show a not-found
message with an app search, rather than an error.

#### Scenario: Anonymous visitor opens a deep link
- **WHEN** an anonymous visitor opens `/apps/immich`
- **THEN** the Immich page renders without asking them to sign in

#### Scenario: Unlisted product
- **WHEN** a visitor opens the page of a product whose visibility is
  `unlisted`
- **THEN** the product's page renders
- **AND** it carries a `robots` `noindex` meta tag

#### Scenario: Public product is indexable
- **WHEN** a visitor opens the page of a `public` product
- **THEN** the page carries no `robots` `noindex` meta tag

#### Scenario: Unknown slug
- **WHEN** a visitor opens `/apps/` followed by a slug no listed product has
- **THEN** the page shows the not-found message and the app search
- **AND** it carries a `robots` `noindex` meta tag

## ADDED Requirements

### Requirement: The catalog at /apps lists every storefront app
The UI SHALL serve `/apps` to anonymous and signed-in visitors as the place to
browse apps, with the public site navigation and footer. It SHALL show one row
per storefront product with its icon, name, tagline, category, the lowest
monthly price of its paid plans (or that it is free), and, when the product
declares `replaces`, the line "An alternative to" followed by those names. For
a signed-in visitor, a row SHALL show how many deployments of that app they
run.

#### Scenario: Anonymous visitor browses
- **WHEN** an anonymous visitor opens `/apps`
- **THEN** every `public` product is listed without asking them to sign in

#### Scenario: App the visitor already runs
- **WHEN** a signed-in visitor running two Immich deployments opens `/apps`
- **THEN** the Immich row says two are running

### Requirement: The catalog filters by search and category in the address
The catalog SHALL filter its rows by a free-text search over each product's
name, tagline, category, `replaces` and description, and by a single selected
category, each category offered with its number of apps. Both SHALL be kept in
the address (`q` and `category`) so that a filtered catalog can be linked.
Pressing `/` outside a text field SHALL focus the search. When no row matches,
the catalog SHALL say so and offer to clear the filters.

#### Scenario: Search by what an app replaces
- **WHEN** a visitor searches the catalog for "google photos"
- **THEN** the apps whose `replaces` names Google Photos are listed

#### Scenario: Filtered link
- **WHEN** a visitor opens `/apps?category=Photos`
- **THEN** only the apps in the Photos category are listed, with that
  category selected

#### Scenario: Nothing matches
- **WHEN** the search matches no app and the visitor selects the offer to
  clear the filters
- **THEN** the search and category are cleared and every app is listed

### Requirement: A catalog row expands into a preview
Selecting a catalog row SHALL expand it in place to a preview showing the
app's screenshots (opening in the full-screen viewer), its features, its plans
with prices, an Install action and a link to the app's page. The preview's
listing content and plans SHALL be requested only when a row is first
expanded.

#### Scenario: Collapsed rows request no listing content
- **WHEN** a visitor opens `/apps` and expands no row
- **THEN** no product's listing content or plans are requested

#### Scenario: Preview links to the full page
- **WHEN** a visitor expands the Immich row and selects its details link
- **THEN** they are on `/apps/immich`

### Requirement: Install from the catalog follows the app page's install
Install in a catalog preview SHALL behave as Install on the app page: for a
signed-in visitor it SHALL open the install flow, with the subdomain claim
first when needed, over the catalog; for an anonymous visitor it SHALL start
sign-up and return them to the app's page with the deploy dialog open. A
chosen plan SHALL carry through in both cases.

#### Scenario: Signed-in install from a row
- **WHEN** a signed-in visitor holding a subdomain selects Install in the
  Vaultwarden preview
- **THEN** the deploy dialog for Vaultwarden opens over the catalog

#### Scenario: Anonymous install from a row
- **WHEN** an anonymous visitor selects Install in the Vaultwarden preview and
  completes sign-up
- **THEN** they land on the Vaultwarden page with its deploy dialog open
