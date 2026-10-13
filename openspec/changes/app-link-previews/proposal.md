## Why

Every catalog app has a public page at `/apps/:slug`, but it is a route in the
single-page app, so nginx serves the same `index.html` for it as for `/`. Link
crawlers don't run JavaScript, so a shared link to the Immich page previews as
the generic Freepod card rather than as Immich.

## What Changes

- The UI build reads `products/catalog` and, for each storefront app, emits
  `app-<slug>.html`: the built `index.html` with that app's title, description
  and Open Graph / Twitter tags, in the same way `dev.html` already serves
  `/dev`.
- The build renders each app a 1200x630 card image (icon, name, category,
  tagline and the services it replaces, in the site card's visual language),
  emitted as a content-hashed asset.
- nginx serves `app-<slug>.html` for `/apps/<slug>` and falls back to
  `index.html` for a slug with no page.
- nginx rewrites the absolute `https://freepod.eu` URLs in the preview tags
  of `/`, `/dev` and the app pages to the requesting host, so dev's previews
  point at dev.
- The UI image's build stage receives the catalog as the docs stage already
  does, through the `catalog` named build context and `CATALOG_DIR`.

Not changed: the page itself, which still renders its content from the API;
no API, catalog format or database change.

## Capabilities

### New Capabilities

- `app-link-previews`: the per-app HTML and card image, their content, and
  how nginx serves them.

### Modified Capabilities

None.

## Impact

- `ui/og/apps.ts` (new): reads the catalog and renders the cards.
- `ui/vite.config.ts`, `ui/src/content/pageMeta.ts`: the `pageMeta` plugin
  emits the app pages.
- `ui/nginx.conf`, `ui/Dockerfile`.
- `ui/package.json`: build-time dev dependencies `satori`, `@resvg/resvg-js`,
  `js-yaml` and the static `@fontsource/fraunces` and
  `@fontsource/schibsted-grotesk` fonts.
