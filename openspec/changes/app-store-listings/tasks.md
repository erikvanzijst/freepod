# Tasks

## 1. Data model and migration

- [x] 1.1 Add text columns `tagline` and `license` and JSON-list columns `features`, `links` and `screenshots` (defaulting to empty) to `ProductORM`, nullable `version` to `ProductTemplateVersionORM` with an index on `(product_id, version)`, and a `ProductReleaseORM` with `(product_id, version)` unique and a `position`; verify the models import and `tests/test_schema_drift.py` passes after 1.2
- [x] 1.2 Write one Alembic migration adding the five product columns, `product_template_version.version` with its `(product_id, version)` index, and `product_release`, with a downgrade removing them; verify migration tests for upgrade on existing rows (null text, empty lists, null versions, no releases) and downgrade

## 2. Catalog format and loader

- [x] 2.1 Extend `ProductBlock` with `tagline`, `license`, `features`, `links` (HTTPS, known kinds) and `screenshots` (`file`, `caption`, `form`, optional `credit`), and make asset paths resolve against the document's folder and stay inside it; verify model tests for each validation error in the product-catalog-format and product-listing-metadata specs
- [x] 2.2 Rewrite `load_catalog` for `products/catalog/<slug>/<slug>.yaml`: reject top-level YAML files and folders without their document, keep slug and duplicate checks; verify loader tests for each scenario of "Published products are declared as catalog files"
- [x] 2.3 Add screenshot validation on load (PNG, JPEG or WebP; at most 1 MB and 4096 px each; at most 12 and 5 MB per product; opened but not re-encoded) and the rendition pipeline in `api/app/services/images.py` (680 px-tall thumbnail and full size up to 2400 px, both WebP, named by source hash and pipeline version, design D7); verify image tests for valid, oversized, too-many and corrupt inputs and for both rendition sizes
- [x] 2.4 Parse and validate `releases.yaml` (list, unique versions, non-empty notes, size limit) into the catalog entry; verify tests for valid, duplicate-version and missing-file cases
- [x] 2.5 Move the schema modeline to `../catalog.schema.json`, regenerate `products/catalog/catalog.schema.json` with `caelus catalog lint --write-schema`, and extend lint to cover the new layout, screenshots and releases; verify `tests/test_catalog_cli.py` lint scenarios including missing screenshot and duplicate release version

## 3. Reconciler

- [x] 3.1 Apply `tagline`, `description`, `license`, `features` and `links` in `_apply_document`, and leave them untouched in `_release_undeclared`; verify reconcile tests that a tagline change inserts no template and that uncurating keeps listing data
- [x] 3.2 Materialize screenshot renditions into static storage (process only when a rendition file is missing, verify both on disk, store `{path, caption, form, credit}` in order) and record `screenshot-materialized` actions; verify tests for first run, unchanged rerun, repopulating a missing thumbnail, and unreadable image aborting the run
- [x] 3.3 Stamp `version` on inserted templates and fill null versions of a curated product's existing rows from the current `upstream` block (design D2/D3), recording `version-stamped` actions; verify tests for image-tag paths, `template.chart_version` paths, non-matching values, and never overwriting a set version
- [x] 3.4 Sync `product_release` rows with `releases.yaml` (insert, update notes or position, delete) and record release actions; verify tests for each scenario of "The reconciler keeps releases in sync with the releases file" and that a dry run reports without writing
- [x] 3.5 Update the module docstring and `api/README.md` catalog section to describe the per-product folder, the version stamping exception and release syncing; verify the README links still resolve

## 4. Curate

- [x] 4.1 Make `catalog curate` write `<slug>/<slug>.yaml` and `<slug>/icon.png` with the listing text fields, and update `catalog_file_for` and the curated write-guard messages to the new path; verify the round-trip test inserts no template and the guard tests name `products/catalog/<slug>/<slug>.yaml`

## 5. API and CLI

- [x] 5.1 Add `tagline` to `ProductReadBase` and `version` to the template read, and introduce `ProductSummary` (`id`, `name`, `slug`, `icon_url`, `tagline`, `template_id`) for `ProductTemplateVersionRead.product` (design D11); verify API tests that product lists carry `tagline` but no listing content and that deployment and template responses nest only the summary fields
- [x] 5.2 Add `GET /api/products/{product_id}/listing` returning license, features, links, screenshots (`thumbnail_url`, `url`, caption, form, credit) and `version` plus `version_available_at`, in one product read and one aggregate (design D4/D11); verify API tests for anonymous access, declared order, a chart bump keeping the date, null version, empty listing and 404
- [x] 5.3 Serve `/api/static` with `Cache-Control: public, max-age=31536000, immutable` (design D12); verify a test that an icon response carries the header
- [x] 5.4 Accept `tagline`, `license`, `features` and `links` on `ProductCreate`/`ProductUpdate` (not `screenshots`), rejected for curated products by the existing guard; verify API tests for partial update, invalid link, unknown `screenshots` field and curated rejection
- [x] 5.5 Add `GET /api/products/{product_id}/releases` returning a plain array of `version`, `notes` and `available_at`, newest first and unpaginated, in one query joining the per-version template aggregate, with the product's read access; verify tests for anonymous access, empty list, null `available_at`, and 405 on writes
- [x] 5.6 Add `create-product`/`update-product` options (`--tagline`, `--license`, `--features-file`, `--links-file`) and `get-product-listing` and `list-product-releases` commands; verify CLI parity tests against the API behavior
- [x] 5.7 Document the new fields, the summary nesting and both endpoints in the `api/app/api/products.py` endpoint docs and `api/README.md`; run the full `api/` pytest suite and verify it is green
- [x] 5.8 Add `GET /api/products/{id}/listing` and `GET /api/products/{id}/releases` to oauth2-proxy's `skip_auth_routes` in `tf/app/login/main.tf` and to the public endpoint list in `api/README.md`; verify an anonymous `curl` against dev returns 200 for both

## 6. Catalog content

- [x] 6.1 Move every product to `products/catalog/<slug>/` (document, `icon.png`), removing `products/catalog/icons/`; verify `caelus catalog lint` passes
- [x] 6.2 Move the fixture content from `ui/src/components/apppage/listingContent.ts` into each document: the current one-line `description` becomes `tagline`, the paragraphs become a Markdown `description`, plus `license`, `features` and `links`; verify lint and a dry-run `catalog apply` against a local database show only the expected field updates
- [x] 6.3 Move the screenshots from `ui/public/mockups/<slug>/` into each `screenshots/` folder with captions, forms and credits, and Immich's release notes into `products/catalog/immich/releases.yaml`; verify a local `catalog apply` materializes every screenshot and the API returns them with credits
- [x] 6.4 Update `scripts/build-images.sh` messages and every `products/<slug>/README.md` and `AGENTS.md` reference to the old file paths; verify `grep -rn "products/catalog/[a-z-]*\.yaml"` finds no stale references outside `openspec/`

## 7. Docs portal

- [x] 7.1 Make `ui/docs/src/plugins/catalog.mjs` read `<slug>/<slug>.yaml` and serve each product's icon from its folder, and update the docs config's static directories; verify the docs site builds and every app page shows its icon

## 8. Upgrader

- [x] 8.1 Widen the patch allowlist in `ops/upgrader/upgrader/proposal.py` to `products/catalog/<slug>/` and `products/<slug>/`, and make `ops/upgrader/upgrader/catalog.py` discover per-product folders; verify upgrader tests for an allowed `releases.yaml` change, a refused `catalog.schema.json` change and another product's folder
- [x] 8.2 Update `products/UPGRADING/SKILL.md` paths and add the release-entry step and its rules (user-facing, no links or mentions, valid under lint); verify the skill's checklist mentions `releases.yaml` and `uv run pytest` in `ops/upgrader` passes

## 9. App page and landing

- [x] 9.1 Add `tagline` to the UI product type, a `ProductSummary` type for nested products, `version` to the template type, and `getProductListing` and `listReleases` endpoints with their types; verify `npx tsc -b` with deployment cards and dialogs compiling against the summary
- [x] 9.2 Rebuild `useAppListing` on the product, plans, listing and releases endpoints only, render the description as Markdown without raw HTML, use thumbnails in the strip and full-size images only in the viewer, show screenshot credits, and delete `listingContent.ts` and `ui/public/mockups/`; verify component tests for a fully populated product, one with only a name and plans, and that the strip never requests a full-size URL
- [x] 9.3 Switch landing cards to `tagline` with no fallback to `description` and link each card to `/apps/:slug`; verify landing tests for the blurb, the missing-tagline case and the link
- [x] 9.4 Extract the claim-then-deploy sequence into an `InstallFlow` component used by the Dashboard and the app page; make Install open it over the app page through `?install=1&plan=<id>`, let `useStartSignup` carry that return path (oauth2-proxy `rd` and the dev email dialog), give `DeployDialog` an initial plan and an `onLaunched` callback, and move to the dashboard only after a launch; verify tests for signed-in install, cancel and launch, the subdomain-claim gate, anonymous return, and stale parameters
- [x] 9.5 Add tagline and license inputs and a multi-line description to the admin product form, read-only for curated products, and show the tagline instead of the description in `DeployDialogContent`'s header; verify admin form tests and deploy dialog tests for both tagline cases
- [x] 9.6 Run eslint on touched files and the full vitest suite and verify both are clean

## 10. Integration

- [x] 10.1 Against a local database: run migrations and `catalog apply`, then check in the browser that every `/apps/:slug` page shows its content, version, date and screenshots, that Immich shows its release notes, and that Install reaches a preselected deploy dialog both signed in and through the dev sign-up
- [x] 10.2 Check in the browser's network panel that an app page loads only thumbnails until the viewer opens, and that a second visit serves icons and screenshots from cache
- [x] 10.3 Validate the change with `openspec validate app-store-listings --strict`

## Workflow follow-up

- Archive with `openspec archive app-store-listings` after the PR is merged and rolled out, syncing the delta specs; that creates the `product-listing-metadata`, `product-releases` and `app-listing-page` main specs `api/README.md` already links to.
