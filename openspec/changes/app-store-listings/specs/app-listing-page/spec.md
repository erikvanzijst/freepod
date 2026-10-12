## Purpose

Give every storefront app a public, deep-linkable page at `/apps/:slug` that
presents it like an app-store listing and lets a visitor start a deployment of
it, whether or not they are signed in.

## ADDED Requirements

### Requirement: Each storefront product has a public page
The UI SHALL serve `/apps/:slug` to anonymous and signed-in visitors alike,
with the public site navigation and footer, for every product whose visibility
is `public` and whose slug equals `:slug`. Any other slug SHALL show a
not-found message with an app search, rather than an error.

#### Scenario: Anonymous visitor opens a deep link
- **WHEN** an anonymous visitor opens `/apps/immich`
- **THEN** the Immich page renders without asking them to sign in

#### Scenario: Unlisted product
- **WHEN** a visitor opens the page of a product whose visibility is
  `unlisted`
- **THEN** the page shows the not-found message and the app search

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
