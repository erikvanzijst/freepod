# Design

## Context

See proposal.md for motivation. The relevant current state:

- `api/app/services/catalog.py` loads top-level `products/catalog/*.yaml`
  files (via `iterdir`), validates them with Pydantic models (`ProductBlock`,
  `UpstreamBlock`, `TemplateBlock`), and reconciles them in one transaction
  under an advisory lock. Product fields are applied in place on every run;
  templates are matched by a spec hash over five fields and otherwise only
  inserted. Icons are processed (`process_icon`), content-addressed
  (`generate_icon_filename`) and verified on disk in static storage.
- The `upstream` block (`source`, `match`, `version_path`) is only read by the
  upgrader and never stored, so the database cannot tell which version a
  template deploys.
- The upgrader (`ops/upgrader/`) discovers products with
  `products/catalog/*.yaml` and refuses patches outside
  `products/catalog/<slug>.yaml` and `products/<slug>/`. Its skill
  (`products/UPGRADING/SKILL.md`) already gathers release notes for every
  skipped-over release into the PR description.
- The app page (`ui/src/pages/AppPage.tsx`, `ui/src/components/apppage/`) merges
  the live product and plans with the `LISTING_CONTENT` fixture; the
  Dashboard owns the deploy dialog, gated on claiming a subdomain first, and
  is the only place an app can be installed from.
- Sign-up in production goes through oauth2-proxy (`/oauth2/start?rd=...`); in
  local development an email dialog stands in for it.

## Goals / Non-Goals

**Goals:**
- Listing content, version and releases reach the app page only through the
  API, sourced from the catalog for curated products.
- Each product's catalog content is one self-contained folder, so a reviewer,
  `catalog lint` and the upgrader's allowlist all work per product.
- Install goes from any app page to a preselected deploy dialog, surviving the
  sign-up redirect.

**Non-Goals:**
- The `/apps` index page (the page already links to it; built separately).
- Editing features, links or screenshots in the admin UI, and uploading
  screenshots through the API. Non-curated products get text fields only.
- Deleting orphaned screenshot files from static storage (icons don't either).
- Localized listing content.
- A product lookup by slug in the API; the client filters the (small) product
  list, as the landing page already does.

## Decisions

### D1. Listing fields live on the product row, not the template
`tagline`, `license`, `features`, `links` and `screenshots` are columns on
`product` (JSON for the lists), applied in place by the reconciler like
`category`. Putting them on `product_template_version` would make a typo fix in
a feature bullet mint a new deployable template, change the spec hash, and
duplicate the copy across every version. The description stays in the existing
`description` column, which now holds Markdown.

### D2. The version is stamped by the reconciler, not computed on read
The reconciler applies the document's `upstream.match` to the value at
`upstream.version_path` when it inserts a row, and stores the `version` named
group (`3.3.1`, not `v3.3.1`). Computing it on read is impossible because the
upstream block is not in the database; the paths differ per product
(`template.system_values.image.tag`, `template.chart_version`, ...); raw tags
(`v3.3.1`, `35.0.1-apache`, `261007`) need the Python-syntax regex to
normalize; and non-catalog products have no recipe at all. Storing the
normalized group gives one comparable value for the page, the releases join
and later features.

`version_path` is resolved against the row by mapping `template.chart_ref`,
`template.chart_version` and `template.chart_digest` to the columns and
`template.system_values.<a>.<b>` into `system_values_json`. Any other path, or
a path that does not resolve, yields null.

### D3. Backfill is a fill-null pass on every run
Instead of a one-off script, each run walks the curated product's template rows
with a null `version` and stamps those the current upstream rules can derive.
It is idempotent, covers rows from before this change, and needs no separate
deployment step. It never touches a non-null version (spec:
catalog-reconciliation), so a later change to `match` cannot rewrite history.
This is the one sanctioned write to an existing template row; `version` stays
out of the spec hash, so matching is unaffected.

### D4. The availability date is derived on read
`version_available_at` and each release's `available_at` are
`min(created_at)` over the product's non-deleted template rows with that
version, computed in the read query. Storing it would duplicate data the rows
already hold and drift when templates are added. Chart-only bumps insert new
rows with the same version, so the minimum keeps the date of the first one.

### D5. Releases are a table synced from `releases.yaml`
`product_release (id, product_id, version, notes, position, created_at,
updated_at)`, unique on `(product_id, version)`. The reconciler makes the rows
equal the file: insert, update notes or position, delete. The file is ordered
newest first and `position` keeps that order, which is more reliable than
sorting version strings across products' formats. Keeping notes out of the
template avoids the hash, typo and duplication problems of D1, and lets an
operator correct old notes without touching any template.

### D6. One folder per product, paths relative to the folder
```
products/catalog/
  catalog.schema.json
  immich/
    immich.yaml        # product, upstream, template blocks
    icon.png
    screenshots/*.webp
    releases.yaml
```
The document is named `<slug>.yaml`, not `product.yaml`, so editor tabs and
search results are unambiguous. Asset paths resolve against the document's
folder and must stay inside it, which is what lets the upgrader allowlist be
the folder. The modeline becomes `../catalog.schema.json`. The loader treats
any top-level YAML file as an error naming the expected folder, so a stale
branch on the old layout fails loudly in CI rather than being ignored.

### D7. Screenshots are capped in the repo and published in two renditions
Committed screenshots are capped at 1 MB and 4096 px each, 12 per product and
5 MB per product, enforced by the loader so `catalog lint` catches them. That
bounds the repository and the API image; what visitors download is bounded by
the renditions. Each screenshot becomes two WebP files in static storage:

- a thumbnail for the page's strip, 680 px tall (the strip's 340 CSS px at 2×
  density), typically tens of kilobytes;
- a full-size image, long edge at most 2400 px, fetched only when the viewer
  opens.

Both live at `screenshots/<hash>-thumb.webp` and `screenshots/<hash>.webp`,
where the hash covers the source bytes and a pipeline version, so changing the
pipeline republishes everything. Loading a document only opens each image to
check its format, size and dimensions; the reconciler decodes and encodes a
screenshot only when one of its files is missing from the volume, which keeps
rollouts fast and still repopulates an empty volume. The product row stores
`{path, caption, form, credit}`; the read schema derives `thumbnail_url` and
`url` from `path` the way it derives `icon_url`.

Static files are served by the API from the `caelus-static-pvc` volume at
`/api/static`, which the catalog init container also mounts; the web UI
container is not involved.

### D8. Install opens over the app page via URL parameters
The claim-then-deploy sequence moves out of the Dashboard into a shared
`InstallFlow` component: the subdomain claim when the user holds none, then
`DeployDialog` with an initial plan. The Dashboard uses it when an app is
picked, and the app page uses it for Install, so the dialog opens over the page
the visitor is on and closing it leaves them there. Only a successful launch
moves to the dashboard; a paid launch goes there through the checkout's return
URL.

The request lives in the app page's own URL, `/apps/<slug>?install=1&plan=<id>`,
and is removed with a history replace when the flow ends. For an anonymous
visitor, `useStartSignup` takes that URL as its return path: in production it
becomes oauth2-proxy's `rd`, and in development the email dialog navigates
there after setting the email. URL parameters survive the Keycloak round trip,
which component state and session storage on another origin do not. A request
for an undeployable product, or from a visitor who is still anonymous, opens
nothing.

### D9. The UI keeps only presentation
The `LISTING_CONTENT` fixture and `ui/public/mockups/` are deleted; their
content and images move into the catalog folders with their credits. The
feature icon map (key to icon component) stays in the UI, falling back to a
generic icon. The description is rendered with the existing Markdown renderer,
with raw HTML disabled. Releases are fetched from their own endpoint so the
product list stays small.

### D10. The upgrader writes the release entry in the same patch
The skill's step that already collects upstream notes also produces a short
user-facing entry and prepends it to `releases.yaml`. Because it is part of the
patch, a reviewer edits it in the same PR, `catalog lint` validates it in CI,
and the reconciler publishes it on rollout. No new upgrader output file or
service check is needed beyond the widened allowlist.

### D11. Heavy listing content has its own endpoint; nested products are summaries
Product reads (`GET /api/products`, `GET /api/products/{id}`) gain only
`tagline`. Everything else the app page needs (license, features, links,
screenshots, `version`, `version_available_at`) comes from
`GET /api/products/{id}/listing`, and releases from their own endpoint, so the
landing page, pricing and dashboard never download listing content they do not
render.

`ProductReadBase` is also what `ProductTemplateVersionRead.product` nests,
which every deployment response carries through `desired_template`. That
nesting switches to a `ProductSummary` (`id`, `name`, `slug`, `icon_url`,
`tagline`, `template_id`): the UI reads only those fields from nested products
(deployment cards use name and icon; the deploy dialog uses id, name, icon,
`template_id`, and now the tagline). Descriptions are only about half a
kilobyte today, but the summary keeps nested payloads from growing with every
field a product gains.

Query cost is kept flat by construction rather than measured by tests:

- the listing is one product read (canonical template joined, as today) plus
  one `min(created_at)` aggregate for the version date;
- releases are one query joining `product_release` to a per-version
  `min(created_at)` aggregate over the product's templates;
- the product list adds only a column.

Two indexes back this: `(product_id, version)` on `product_template_version`
for the aggregates, and the unique `(product_id, version)` on
`product_release`, which also serves listing a product's releases.

### D12. Content-addressed static files are cached immutably
Starlette's `StaticFiles` sends `ETag` and `Last-Modified` but no
`Cache-Control`, so browsers revalidate every icon and screenshot. Because
every file under `/api/static` is named by its content hash, the mount gets a
`Cache-Control: public, max-age=31536000, immutable` header. A changed image
gets a new name, so the long lifetime never serves stale content.

## Risks / Trade-offs

- [Third-party screenshots carry license terms] → Every borrowed image keeps a
  `credit` with its license and source link, shown in the viewer; images under
  share-alike or attribution licenses are only resized and re-encoded.
- [The catalog move breaks open branches and upgrade PRs] → Land it when no
  upgrade PR is open; the loader rejects old-layout files with a message naming
  the new folder, and the nightly run picks up the new layout from `master`.
- [Images in the repository and API image] → Capped at 5 MB per product and
  in practice well under 2 MB; visitors download thumbnails first.
- [LLM-written release notes may be wrong or too long] → They arrive in the
  upgrade PR for review, and lint enforces the size limit.
- [A wrong `match` stamps a wrong version forever] → Stamping only fills nulls,
  so a bad value can be corrected by setting it back to null by hand and
  re-running apply; the curated-product guard keeps the API from writing it.
- [Static storage keeps old screenshots] → Small, and safe: a rollback to an
  older image still finds its files.
- [The nested product summary drops fields API clients may read] → The UI
  reads only summary fields from nested products, and the `freepod` client
  reads the top-level product list and the template's own fields, never a
  nested product. Third-party scripts reading nested descriptions would break;
  there is no supported contract for them.

## Migration Plan

1. One pull request carries the Alembic migration, the API, reconciler,
   upgrader and UI changes, and the catalog moved to the new layout with the
   fixture content and images.
2. On rollout the init container runs migrations, then `catalog apply`, which
   stamps versions on existing templates, materializes screenshots and loads
   releases. The landing cards show taglines from the same rollout, so there is
   no transition period.
3. Rollback: redeploy the previous image. Its code ignores the new columns and
   table and its baked-in catalog uses the old layout, so no downgrade is
   needed; the downgrade exists for completeness.
