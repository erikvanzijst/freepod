## Why

Apps built in App Studio start from its starter and follow its agent's
instructions, so both should follow current browser hardening practice from
the first commit: data changed only by the app's own pages, framing refused,
cookies host-bound, and uploads and user text never served as markup.

The studio's start-up script still moves a single-app workspace into the apps
directory, and every studio has used the apps directory layout for some time.

## What Changes

- **Starter request origin:** a new `server/same-origin.ts` middleware refuses
  `POST`, `PUT`, `PATCH` and `DELETE` requests a browser started from a page on
  another origin. Requests without browser origin headers (curl, webhooks) pass.
- **Starter framing:** every page and API response carries
  `Content-Security-Policy: frame-ancestors 'self'`,
  `X-Frame-Options: SAMEORIGIN` and `X-Content-Type-Options: nosniff`, in
  production and in the preview, unless the app sets them itself.
- **Agent instructions:** a section of rules for the user's data: changes only
  through `POST`/`PUT`/`PATCH`/`DELETE`, no CORS, identity only from Sign in
  with Freepod, `__Host-` cookies, uploads as downloads, user text as text. Apps
  started before the middleware existed get it from the starter.
- **Layout migration removed:** the studio no longer moves `/workspace/app` to
  `/workspace/apps/app` on start, and its page no longer drops a
  `/workspace/app` entry from the browser's opencode project list.
- Image 0.1.28, chart 0.2.14.

## Capabilities

### New Capabilities

- `app-studio-starter`: what the starter app and the agent's instructions
  guarantee about requests from other origins, framing and user content.

### Modified Capabilities

- `app-studio-projects`: drops the one-time move of the single-app layout and
  the removal of its entry from the project list.

## Impact

- `products/appstudio/image/template/` and `examples/`: `server/same-origin.ts`,
  `server/index.ts`, README layout row.
- `products/appstudio/image/AGENTS.md`, `bin/appstudio-start`,
  `chart/files/index.html`.
- Existing apps keep their code until the agent next works on them and adds the
  middleware from the starter.
