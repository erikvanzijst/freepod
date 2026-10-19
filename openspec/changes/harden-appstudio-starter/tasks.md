## 1. Starter

- [x] 1.1 Add `server/same-origin.ts` (origin check on state-changing methods, page headers) to the starter and the examples
- [x] 1.2 Use it in `server/index.ts` for every Hono response, and set the page headers on what Vite serves in development
- [x] 1.3 Add the file to the starter README's layout table

## 2. Agent and studio

- [x] 2.1 Add the user-data rules to `AGENTS.md`, including how an older app adopts the middleware
- [x] 2.2 Remove the `/workspace/app` move from `appstudio-start` and the legacy project-list entry handling from the chrome's `index.html`
- [x] 2.3 Bump the image to 0.1.28 and the chart to 0.2.14 (values, `Chart.yaml`, catalog)

## 3. Verification

- [x] 3.1 Type-check the starter; in production and development mode, same-origin and header-less `POST`s pass, `same-site`/`cross-site` and foreign `Origin` `POST`/`DELETE` get `403`, `GET`s pass, and pages, API responses and Vite modules carry the headers
- [x] 3.2 In Chrome: the starter renders without console errors, its own `fetch` `POST`s succeed, another origin's `no-cors` and form `POST`s change nothing, and its frame is refused; with the middleware removed, the same test sees both get through
- [ ] 3.3 Publish image 0.1.28 and chart 0.2.14; in a dev studio, a new app from the starter runs in the preview and the agent's `curl` checks still pass
- [ ] 3.4 Move the dev studios, then the prod studios, to chart 0.2.14
