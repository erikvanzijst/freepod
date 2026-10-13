## 1. Build

- [x] 1.1 Read storefront apps from the catalog and render each a card with satori and resvg (`ui/og/apps.ts`), with tests for the reader and the card's size
- [x] 1.2 Add `appPageMeta` to `ui/src/content/pageMeta.ts` and emit `app-<slug>.html` and the hashed card from the `pageMeta` plugin, with tests
- [x] 1.3 Pass the catalog to the UI image's build stage

## 2. Serving

- [x] 2.1 Map `/apps/<slug>` to `app-<slug>.html` in `ui/nginx.conf`, falling back to `index.html`, and verify against a local nginx

## 3. Integration

- [x] 3.1 Run `npx tsc -b`, eslint on touched UI files, vitest and `npm run build`
- [x] 3.2 Validate the change with `openspec validate app-link-previews --strict`

## Workflow follow-up

- Archive the change after merge, syncing the delta into
  `openspec/specs/app-link-previews/spec.md`.
