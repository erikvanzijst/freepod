## Why

Every `custom` app reserves a 128Mi memory request, whatever it runs. Railpack serves
every static site and Node SPA with Caddy, and those measure at roughly 10–11 MiB
working set, so each one reserves about twelve times what it uses. A container's
memory request is the floor an idle instance is billed at (usage above it is billed
on its own), so static sites are overcharged for memory they never touch. The build
already knows which images are static sites: Railpack's build plan names Caddy as the
start command.

## What Changes

- The builder reads the Railpack build plan it already writes and reports whether the
  image serves a static site with Railpack's Caddy, alongside the image in its
  termination message. A Dockerfile build, or a plan that is missing, unreadable or
  does anything else, is reported as not a static site.
- The build worker stores that verdict on the build, so it is platform-held state
  derived from the build rather than anything a tenant submits.
- The reconciler projects the facts of the build a release names, `caelus.build.image`
  and `caelus.build.staticSite`, into every release's system values. Tenants cannot
  shadow them, because system overrides are applied last.
- The `custom` chart (0.14.0) gives the application container a smaller request,
  `staticSiteResources` (16Mi memory), only when the image it actually runs is the one
  that static build produced. Anything else keeps `resources` (128Mi). Requests only:
  no limits are added.
- Builder image 0.5.0, which writes the new field, and a database migration adding
  the build column.

## Capabilities

### New Capabilities

- `static-site-sizing`: how a static-site build reaches the release that runs it, and
  the request the `custom` chart renders for it.

### Modified Capabilities

- `build-execution`: the build detects a Railpack static site from its plan and
  reports the result with its image.
- `build-data-model`: a build records whether its image serves a static site.
- `build-worker`: the worker stores that verdict when it observes the build succeed.

## Impact

- `products/custom/builder/build.py`, `VERSION`: plan inspection and the new
  termination field.
- `api/app/models/build.py`, a new Alembic migration, `api/app/build_worker.py`,
  `api/app/services/build_jobs.py`: parse and store the verdict.
- `api/app/services/reconcile.py`: the `caelus.build` projection.
- `products/custom/chart` (values, schema, template, version) and
  `products/catalog/custom/custom.yaml` (chart version).
- Order of publishing: the builder image (and its Terraform pin) and the chart must
  be published before the catalog points at the new chart. Existing deployments
  switch over when they are next built and deployed, which moves them to the new
  canonical template too.
- `ui/docs/developers/usage-and-billing.md`: the lower minimum for static sites.
- No API contract change. `freepod` is unaffected.
