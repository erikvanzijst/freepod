# Immich — Freepod chart

A self-contained Helm chart for [Immich](https://immich.app/), a self-hosted
photo and video library. The chart renders the entire deployment directly; its
only dependency is Freepod's own `ssh-sidecar` library chart (which provides the
read-only file access to the photo library).

## What it deploys

| Component | Object(s) |
|-----------|-----------|
| Server (web/API) | Deployment `<release>-server` (+ SSH sidecar), Service `:2283` |
| Machine learning | Deployment `<release>-machine-learning`, Service `:3003` |
| Valkey (queue) | Deployment + PVC `<release>-valkey` + Service `:6379` |
| PostgreSQL (vectorchord) | Secret + PVC `postgresql-data` + Service + Deployment |
| Library | PVC `library` (plan-sized) |
| Config | ConfigMap `<release>-config` (external URL, SMTP, Sign in with Freepod) |
| Ingress | `<release>-ingress` (per-deployment TLS via `caelus.ingress.tls`) |
| File access | Service `<release>-ssh` only (`ssh-sidecar`); session rooted at `volume:/library` |

PostgreSQL uses Immich's own `ghcr.io/immich-app/postgres` image (the
`vectorchord`/`pgvecto.rs` build); stock PostgreSQL will not work because Immich
requires the vector extension. The `library` and `postgresql-data` PVCs use
fixed names (not release-prefixed) so that an existing volume in the namespace
is re-adopted on upgrade rather than replaced by a fresh, empty one.

## Manual install

```bash
helm dependency build products/immich2/chart
helm upgrade --install immich products/immich2/chart \
  --namespace immich --create-namespace \
  --set host=photos.example.com
```

`image.tag` defaults to the chart `appVersion`; override it to pin an Immich
release. Set `smtp.host`/`smtp.from` to enable notification email.

## Build and publish

Published to `oci://ghcr.io/erikvanzijst/freepod/charts/immich` by
[`scripts/publish-charts.sh`](../../scripts/publish-charts.sh), which CI runs on
every merge to `master`: bump `version` in `chart/Chart.yaml` and that version
is published. To publish by hand, from the repository root:

```bash
./scripts/publish-charts.sh immich
```

The published chart is then referenced from a Caelus product template:

| Field               | Value                                                                               |
|---------------------|-------------------------------------------------------------------------------------|
| Chart ref           | `oci://ghcr.io/erikvanzijst/freepod/charts/immich`                                  |
| Chart version       | `0.4.1`                                                                             |
| User values schema  | see [Caelus product template](#caelus-product-template) below                       |
| Default Helm values | see [Default values (system_values_json)](#default-values-system_values_json) below |

## Caelus product template

The **user values schema** defines the form fields on the user-facing deployment
dialog — i.e. the only values a tenant may override when creating an Immich
instance. Everything else (images, storage sizing, DB credentials, TLS) is
operator- or plan-controlled and is deliberately *not* exposed here. It is a
narrow projection of the chart's full `values.schema.json`, not the same file.
The single field is the hostname, which maps to the chart's top-level `host`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "host": {
      "title": "Hostname",
      "type": "string",
      "minLength": 1,
      "description": "The hostname for your Immich instance"
    }
  },
  "required": ["host"],
  "additionalProperties": false
}
```

## Default values (system_values_json)

Separate from the user schema, the admin configures a static **default values**
blob (`system_values_json`) on the product template. It is merged over the
chart's `values.yaml` for *every* deployment created from that template, and is
where operator-wide settings live — SMTP, a pinned image tag and Sign in with
Freepod. It is **not**
where per-tenant values (the domain name) or plan-injected values (storage
sizing) go.

```json
{
  "image": {
    "tag": "v3.4.2"
  },
  "smtp": {
    "host": "smtp.mailer.svc.cluster.local",
    "port": 25,
    "from": "immich@freepod.eu"
  },
  "auth": {
    "enabled": true,
    "protocol": "oidc",
    "access": "listed",
    "oidc": {
      "redirectPaths": ["/auth/login"],
      "nativeRedirectUris": ["app.immich:///oauth-callback"],
      "backchannelLogoutPath": "/api/oauth/backchannel-logout"
    }
  }
}
```

`image.tag` pins the Immich release (otherwise it floats on the chart
`appVersion`); leave `smtp.host` empty to disable notification email.

## Sign in with Freepod

With `auth.enabled` and `auth.protocol: oidc`, Immich signs in only through the
platform's OpenID Provider, the owner becomes its first admin, and the
deployment's access list decides who else gets in. The chart refuses to render
without the values the reconciler injects (`caelus.oidc.*`,
`caelus.owner.email`) or without `auth.access: listed`. Immich's own Create user
is hidden with its custom CSS, since an account created there admits nobody.
Without `auth`, the chart renders Immich with password sign-in.

Spec: [immich-sso](../../openspec/specs/immich-sso/spec.md),
[app-oidc-chart-contract](../../openspec/specs/app-oidc-chart-contract/spec.md),
[app-access-list](../../openspec/specs/app-access-list/spec.md).

## Upstream references

What a version upgrade has to review beyond the tag in
[`products/catalog/immich/immich.yaml`](../catalog/immich/immich.yaml), whose `upstream` block
detects new releases.

- **Release notes:** GitHub releases of `immich-app/immich`.
- **Reference deployment:** `immich-app/immich` at the release tags:
  `docker/docker-compose.yml`, `docker/docker-compose.rootless.yml`,
  `docker/example.env`, `docker/hwaccel.*.yml`, and the runtime stages of
  `server/Dockerfile` and `machine-learning/Dockerfile`.
- **Official chart:** `immich-app/immich-charts`, `charts/immich`, tagged
  `immich-<chart version>`. Its `appVersion` names the Immich release a chart
  version targets.
- **Images:** one tag drives both `ghcr.io/immich-app/immich-server` and
  `ghcr.io/immich-app/immich-machine-learning`, so both must exist.
- **Major versions:** each X.0.0 release note links a migration guide (v3:
  `https://immich.app/blog/v3-migration`). It lists removed env vars, database
  and hardware requirements that the release notes only summarize.

Pitfalls:

- `postgresql.image` is pinned by digest to the image upstream's
  `docker-compose.yml` uses. When upstream moves it (a new vectorchord
  version), this chart has to follow, and the database usually needs a
  migration.
- Valkey floats on `valkey/valkey:9.0-alpine`, while upstream pins a digest of
  `valkey:9`. An upstream digest bump needs nothing here; a new major version
  does.
- The machine-learning container keeps its caches on the `/cache` emptyDir
  (`TRANSFORMERS_CACHE`, `HF_XET_CACHE`, `MPLCONFIGDIR`). Since v3.2.0 the image
  also sets `HF_HOME=/cache/hf-cache` itself. If upstream adds a cache location
  outside `/cache`, it needs the same treatment.
- Since v3.4.0 upstream's default compose sets
  `MACHINE_LEARNING_MODEL_REVISION: v2` on the machine-learning service (the
  newer model exports; unset means the original ones). The chart mirrors it in
  `templates/machine-learning.yaml`; if upstream changes the revision, follow
  it there.
- **Check on every upgrade: the Create user CSS.** `theme.customCss` in
  `templates/config.yaml` hides Create user by hiding the header actions of
  the one page that links to `/admin/users/<id>` and not to
  `/admin/library-management/<id>`: Admin → Users. External Libraries also
  links to its libraries' owners, hence the exclusion. When the rule stops
  matching, nothing fails: the button just comes back, or other header
  actions disappear. Read these files at the current and the new tag
  (`gh api -H 'Accept: application/vnd.github.raw' "repos/immich-app/immich/contents/<path>?ref=<tag>"`)
  and confirm the rule still holds:
  - `web/src/lib/components/BreadcrumbActionPage.svelte`: the page's root
    element has, as a direct child, the header row `div` with classes `h-16`
    and `border-b`; its first child is the breadcrumbs, the actions come after.
  - `web/src/routes/admin/users/(list)/+layout.svelte`: the Users page renders
    through `AdminPageLayout` with only the Create action, and its rows link to
    `Route.viewUser`. `web/src/lib/route.ts` maps that to `/admin/users/<id>`
    and `Route.viewLibrary` to `/admin/library-management/<id>`.
  - Search `web/src` for `viewUser`
    (`gh api -X GET search/code -f q='viewUser repo:immich-app/immich path:web/src'`).
    Every page that renders a link with it, other than the Users page, must
    also link to `/admin/library-management/<id>` or extend the exclusion; at
    v3.4.2 the only one is `library-management/(list)/LibraryTableRow.svelte`.

  If the rule no longer holds, update it in `templates/config.yaml` here and
  in `products/immich-sso`; `api/tests/products/test_immich.py` pins the rule
  and holds both charts equal. Either way, say in the PR what you checked. If
  you can't tell from the source, say so in the PR, so that a person checks
  Admin → Users and Admin → External Libraries (with a library) in a browser
  before merging.
- An existing Immich user is linked to its Freepod account on first sign-in by
  matching email. Upstream PR `immich-app/immich#27871` (tagged for v4)
  replaces that with an explicit link that needs the user's Immich password,
  which SSO turns off; review it before taking the release that ships it.
