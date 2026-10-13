# app-listing-page Specification

## Purpose

Let visitors browse the storefront apps in one catalog at `/apps`, and give
every app a deep-linkable page at `/apps/:slug` that presents it like an
app-store listing. From either, a visitor can start a deployment, whether or
not they are signed in.

## Requirements

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

### Requirement: The page renders listing content from the API
The page SHALL take every piece of listing content from the API: name, icon,
category, replaces, tagline, Markdown description, features, screenshots,
license, links, version, version date, plans and releases. The UI SHALL NOT
carry per-product listing content of its own.

#### Scenario: Content follows the catalog
- **WHEN** a product's tagline changes in its catalog file and the catalog is
  applied
- **THEN** the page shows the new tagline without a UI change

### Requirement: Missing content is omitted, not stubbed
Each section of the page SHALL be omitted when the data it shows is empty or
null: screenshots, features, description, release notes, links, the version
and its date, the license, and the mobile-apps fact (shown only when an `ios`
or `android` link exists).

#### Scenario: Product with only a name and plans
- **WHEN** the page renders a product with no listing fields, no version and
  no releases
- **THEN** it shows the name, the plans and the Install action, and no empty
  sections or placeholders

### Requirement: Screenshots open in a full-screen viewer with their credit
Screenshots SHALL be shown in a scrollable strip in their declared order,
using thumbnails that load lazily, and selecting one SHALL open a full-screen
viewer that pages through the full-size images. Full-size images SHALL load
only once the viewer opens. The viewer SHALL show each caption and any credit,
linked to the credit's `href`.

#### Scenario: Page load fetches thumbnails only
- **WHEN** a visitor opens an app page and does not open the viewer
- **THEN** no full-size screenshot is downloaded

#### Scenario: Credited screenshot
- **WHEN** a visitor opens a screenshot whose credit reads "Nextcloud GmbH and
  contributors · CC BY-SA 4.0"
- **THEN** the viewer shows that credit under the caption

### Requirement: The plan card offers every plan with a sensible default
The page SHALL list all of the product's plans with their prices, and SHALL
preselect the cheapest plan that is not free, or the only plan when there is
one. A plan's one-line summary SHALL be the first line of its description.

#### Scenario: Free and paid plans
- **WHEN** a product has a free plan and paid plans of 5 and 9 euros a month
- **THEN** the 5-euro plan is preselected

### Requirement: Install opens the deploy dialog for a signed-in visitor
For a signed-in visitor, Install SHALL open the existing deploy dialog for
that product over the app page, with the plan chosen on the page preselected.
The dialog's existing gates, such as claiming a subdomain first, SHALL still
apply. Closing the dialog SHALL leave the visitor on the app page; only a
successful launch SHALL take them to the dashboard.

#### Scenario: Signed-in install with a chosen plan
- **WHEN** a signed-in visitor chooses the Pro plan on the Immich page and
  selects Install
- **THEN** the deploy dialog for Immich opens over the Immich page with the
  Pro plan selected

#### Scenario: Install canceled
- **WHEN** the visitor closes the deploy dialog without launching
- **THEN** they are still on the Immich page

#### Scenario: Install launched
- **WHEN** the visitor launches the app from the dialog on a free plan
- **THEN** they are taken to the dashboard

#### Scenario: Subdomain not yet claimed
- **WHEN** a signed-in visitor without a subdomain selects Install
- **THEN** the subdomain claim is asked for first, and the deploy dialog opens
  with the chosen plan once it is claimed

### Requirement: Install by an anonymous visitor resumes after sign-up
For an anonymous visitor, Install SHALL start the sign-up or sign-in flow and,
once it completes, SHALL open the deploy dialog for that product with the
chosen plan preselected, without the visitor having to find the app again.

#### Scenario: Anonymous install
- **WHEN** an anonymous visitor chooses a plan on the Vaultwarden page,
  selects Install and completes sign-up
- **THEN** they return to the Vaultwarden page with its deploy dialog open
  and that plan selected

#### Scenario: Stale install request
- **WHEN** the returning visitor's requested product or plan no longer exists
  or is not deployable
- **THEN** the app page opens without a dialog and without an error page

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
