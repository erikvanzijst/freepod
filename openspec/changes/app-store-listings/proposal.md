# Proposal

## Why

Each catalog app now has a public, store-style page at `/apps/:slug` (tagline,
screenshots, features, description, version, release notes, links and plans),
but everything beyond name, icon, category and plans comes from a hard-coded UI
fixture (`ui/src/components/apppage/listingContent.ts`) and images bundled under
`ui/public/mockups/`. The listing content has to live with each product in the
catalog, travel through the database and API like the rest of the product, and
stay current as the nightly upgrader moves products to new versions. The page's
Install buttons also do nothing yet.

## What Changes

- **Listing fields on the product:** `tagline` (new, one sentence), `license`,
  `features` (title, body, icon key), `links` (label, URL, kind) and
  `screenshots` (image, caption, desktop or mobile form, optional credit). The
  existing `description` becomes the long description, as Markdown.
  **BREAKING:** the landing page's product cards and the deploy dialog switch
  from `description` to `tagline`.
- **Lean responses:** product reads gain only `tagline`; the heavier listing
  content (license, features, links, screenshots, version date) comes from a
  new `GET /api/products/{id}/listing`. Products nested inside template and
  deployment responses shrink to a summary (`id`, `name`, `slug`, `icon_url`,
  `tagline`, `template_id`). **BREAKING** for API clients that read other
  product fields from a nested product.
- **Screenshot delivery:** committed screenshots are capped (1 MB each, 12 and
  5 MB per product), and each is published as a small thumbnail for the page
  and a full-size image loaded only in the viewer. Content-addressed static
  files are served with a long-lived immutable cache header.
- **Product version:** a nullable `version` column on `product_template_version`
  that the catalog reconciler stamps from the document's `upstream.version_path`
  and `upstream.match`. Template reads include it, and the listing endpoint
  adds the moment the canonical version first became available on Freepod (the
  oldest template row carrying it).
- **Release notes:** a `product_release` table (one row per product and version)
  that the reconciler keeps in sync with a per-product releases file, plus an
  endpoint that lists a product's releases.
- **Catalog format:** the `product` block gains the listing fields, screenshots
  are committed image files materialized content-hashed into static storage
  (like icons), and each product's releases file is part of the catalog.
  **BREAKING:** the catalog moves from `products/catalog/<slug>.yaml` plus a
  shared `icons/` folder to one folder per product,
  `products/catalog/<slug>/`, holding `<slug>.yaml`, the icon, `screenshots/`
  and `releases.yaml`. Paths inside a document are relative to that folder.
- **Reconciler:** applies the new product fields in place, materializes
  screenshots, stamps template versions (including existing rows whose version
  can be derived) and syncs releases. `catalog curate` and `catalog lint`
  follow the new layout.
- **Upgrader:** the patch allowlist becomes `products/catalog/<slug>/` and
  `products/<slug>/`, catalog discovery reads the per-product folders, and the
  upgrade skill adds a condensed, user-facing entry to the product's
  `releases.yaml` with every upgrade it proposes.
- **App page:** the UI reads listing content, version and releases from the API
  and the fixture and mockup images are removed. Install opens the existing
  deploy dialog with the chosen plan preselected; an anonymous visitor signs up
  first and lands in that dialog afterwards.
- **Content migration:** the current fixture content and the licensed
  screenshots (with their credits) move into the eight catalog folders.

## Capabilities

### New Capabilities
- `product-listing-metadata`: the listing fields on a product (tagline,
  license, features, links, screenshots), their storage, API and CLI exposure,
  and who may write them.
- `product-releases`: product versions on template rows, the version and
  availability date exposed on a product, and the per-version release notes
  with their API and CLI.
- `app-listing-page`: the public `/apps/:slug` page: what it renders from the
  API, how it degrades when fields are missing, and how Install starts a
  deployment for signed-in and anonymous visitors.

### Modified Capabilities
- `product-catalog-format`: per-product folders, document-relative asset
  paths, the extended `product` block, screenshots and the releases file.
- `catalog-reconciliation`: applying listing fields, materializing
  screenshots, stamping template versions (a narrow exception to append-only
  template rows) and syncing releases.
- `catalog-cli`: `curate` writes a per-product folder.
- `product-marketing-metadata`: a separate `tagline` field now exists and the
  landing page renders it instead of `description`.
- `deploy-dialog-shared`: the dialog's subtitle is the tagline, not the
  description.
- `product-upgrade-runs`: the patch allowlist covers the product's catalog
  folder.
- `product-upgrade-skill`: every proposed upgrade adds a user-facing release
  notes entry.

## Impact

- **Database:** one Alembic migration adding five columns on `product`,
  `version` on `product_template_version`, and the `product_release` table.
- **API:** `api/app/models/core.py` read and write schemas (including the
  nested product summary), `api/app/services/catalog.py` (models, loader,
  reconciler, curate), `api/app/services/images.py` (screenshot renditions),
  listing and releases routes in `api/app/api/products.py`, matching CLI
  commands, the static file mount in `api/app/main.py`, and the regenerated
  `products/catalog/catalog.schema.json`.
- **Catalog content:** every file under `products/catalog/` moves; the API
  Dockerfile already copies the whole directory.
- **Upgrader:** `ops/upgrader/upgrader/proposal.py`,
  `ops/upgrader/upgrader/catalog.py` and `products/UPGRADING/SKILL.md`.
- **UI:** `ui/src/components/apppage/*`, `ui/src/pages/AppPage.tsx`,
  `ui/src/pages/Dashboard.tsx`, `ui/src/components/DeployDialog.tsx` and
  `DeployDialogContent.tsx` (tagline subtitle, nested product type),
  `ui/src/components/landing/*` (tagline, signup return path), and the admin
  product form (tagline, license, multi-line description).
- **Docs:** README and docs pages that describe the catalog layout.
