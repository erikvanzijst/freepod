# Tasks

## 1. Catalog at /apps

- [x] 1.1 Add the `/apps` page with one row per storefront app (icon, name, tagline, category, starting price, "An alternative to", running count), and verify it renders for an anonymous visitor
- [x] 1.2 Filter by search and category kept in `q` and `category`, focus the search on `/`, and offer to clear the filters when nothing matches; verify typing keeps every keystroke and that clearing resets both filters in one update
- [x] 1.3 Expand a row to a preview (screenshots with the viewer, features, plans, Install, details link) that requests its listing content only when expanded
- [x] 1.4 Install from a preview through the app page's install flow, signed in or anonymous, keeping the chosen plan
- [x] 1.5 For administrators, list `unlisted` and `admin` products after the public ones with a visibility badge

## 2. App pages for unlisted products

- [x] 2.1 Resolve `/apps/:slug` against every product the listing returns to the visitor, and verify an unlisted product's page renders
- [x] 2.2 Add a `robots` `noindex` tag to the page of a non-public product and to the not-found message (design D4); verify with a hook test and in the browser against an unlisted, a public and an unknown slug

## 3. Dashboard

- [x] 3.1 Replace the catalog cards and deployment cards with "Your apps" rows, an "Add an app" button and row opening the catalog in a side panel, and starter apps for a user with none; verify a launch from the panel closes the dialog and the panel
- [x] 3.2 Map deployment states to plain-language statuses and gate Open (design D5); verify a unit test per status
- [x] 3.3 Expand rows to details and actions, request file and database access details only on expansion (design D3), and open rows with a problem; verify a test that nothing is requested before expansion
- [x] 3.4 Explain an `error` with the raw message behind "Show details" and a prefilled support email, and show a payment notice for arrears; verify the mailto subject and body in a unit test
- [x] 3.5 Offer Settings for `ready` and `error` deployments
- [x] 3.6 Add search and sort kept in `search` and `sort`
- [x] 3.7 Add the Apps link to the signed-in navigation and hide Developers below the small breakpoint
- [x] 3.8 Remove `DeploymentCard` and its test

## 4. Wording, style and tests

- [x] 4.1 Say "An alternative to" instead of "Replaces" in visitor-facing labels
- [x] 4.2 Lower the theme's corner radii (shape 10, cards 12, list items 8)
- [x] 4.3 Run the debounced-field tests on fake timers (`DeployDialog`, `HostnameField`, `SubdomainField`, `ClaimSubdomain`, `TemplateTabNew`) with Testing Library's `waitFor` driving Vitest's clock; verify the UI suite passes three times in a row
- [x] 4.4 Verify `npm run build`, the UI suite and the full `api/` suite pass
