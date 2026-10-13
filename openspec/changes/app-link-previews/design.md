## Context

`/dev` already has its own link preview: the `pageMeta` Vite plugin writes a
copy of the built `index.html` with that page's tags as `dev.html`, and nginx
maps the path to it. App pages need the same, once per catalog app.

## Decisions

### D1: Rendered at build time from the catalog, not at request time from the API

The catalog folder is the source of truth for listing content, and it reaches
production in the same rollout as the UI image (the docs stage already reads
it). Build-time files keep nginx static and add no runtime dependency on the
API. Alternatives weighed: nginx or a small server rewriting `index.html` per
request from `GET /api/products/{id}/listing` (reflects admin edits made in
the database, at the cost of a new serving path), and prerendering the SPA
with a headless browser (a browser in the build for no gain over the tags).

Consequence: an app that exists only in the database, or an admin edit not
yet in the catalog file, keeps the generic or the catalog's preview until the
catalog says otherwise. Visibility is database-owned, so the build cannot
tell an unlisted catalog product apart; its preview exists while its page
shows not-found. `custom`, which has `/dev`, is skipped as in the docs site.

### D2: A generated card rather than a screenshot

Screenshots are WebP, which several crawlers render poorly or not at all, and
are not the 1.91:1 shape previews crop to. A generated card shows the app's
own icon and tagline and carries the Freepod brand.

### D3: satori and resvg, no browser

`og/generate.sh` rasterizes the site cards with Chrome, which the Alpine
build stage does not have. satori lays out the card as SVG and resvg
rasterizes it, both in Node. satori reads WOFF but not WOFF2 or variable
fonts, hence the static `@fontsource` packages. The icon's glow is a radial
gradient rather than a `box-shadow`, which resvg blurs about ten times slower.

### D4: Hashed image names

Each card is emitted as a Vite asset (`assets/og-<slug>-<hash>.png`), so the
existing immutable caching of static files is correct and a changed card gets
a new URL that crawlers refetch.

### D5: Flat file names

The pages are `app-<slug>.html` at the root, not `apps/<slug>.html`: a
`dist/apps/` directory would make nginx's `try_files $uri/` treat `/apps` as a
directory without an index.
