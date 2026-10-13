# Proposal

## Why

Every app has its own page at `/apps/:slug`, but there is no place to browse
them all: the landing page shows a selection, and the dashboard repeats the
catalog as product cards above the user's deployments. A user with many
deployments scrolls past the catalog to reach their apps, and a visitor cannot
see the full catalog without signing in. The deployment cards also speak in
platform terms (`provisioning`, `error`, raw Helm output) that mean little to
someone who just wants their photos app to work.

Unlisted products are reachable through the API and the CLI, yet their app
page reports them as not found, so there is no page to send someone to.

## What Changes

- **`/apps` catalog:** one public page listing every storefront app as a row
  (icon, name, tagline, category, starting price, "An alternative to"), with
  search and category filters kept in the address. A row expands in place to a
  preview (screenshots, features, plans) with Install and a link to the full
  app page. Install works from the row, signed in or not.
- **Dashboard:** shows only the user's own apps. Each deployment is a row with
  a plain-language status, its address, plan, price and version, and an Open
  button; it expands to its settings, file and database access, and any
  problem. Search and sort apply to the list. Adding an app opens the catalog
  in a side panel, so installing never leaves the dashboard, and a new user
  sees a few starter apps. The signed-in navigation gains an Apps link.
- **Problems in plain words:** a failed change reads as "Needs attention" with
  an explanation, the raw error behind "Show details", and a prefilled email to
  support. A failed payment reads as its own notice.
- **Settings on a failed app:** the Settings action is offered on a
  deployment in `error` as well as `ready`, since saving the settings again is
  the first remedy the notice suggests. The API already accepts an update in
  either state.
- **Unlisted apps by link:** `/apps/:slug` resolves unlisted products (and
  admin-only ones for administrators), and only public app pages may be indexed
  by search engines.
- **Administrators** see unlisted and admin-only products in the catalog, after
  the public ones and badged with their visibility.
- **Wording and style:** "Replaces X" becomes "An alternative to X"; corner
  radii are reduced across the theme.

## Capabilities

### New Capabilities

- `apps-dashboard`: the signed-in dashboard as a list of the user's own apps,
  with the catalog one click away.

### Modified Capabilities

- `app-listing-page`: unlisted products get a page; non-public pages are kept
  out of search results; the `/apps` catalog is added.
- `product-visibility`: the `/apps` catalog is part of the storefront, and
  administrators see non-public products in it.
- `edit-deployment-frontend`: the Settings (Edit) action lives in the
  expanded row and is offered for `error` deployments too.

## Impact

- UI only; no API, schema or catalog changes.
- New: `ui/src/pages/AppsGallery.tsx`, `ui/src/components/appsgallery/`,
  `ui/src/components/dashboard/`, `ui/src/components/deployment/`.
- Removed: `ui/src/components/DeploymentCard.tsx`.
