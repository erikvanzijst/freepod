# PeerTube — Freepod chart

A self-contained Helm chart for [PeerTube](https://joinpeertube.org), a
federated video platform. The chart renders the entire deployment directly;
its only dependency is Freepod's own `ssh-sidecar` library chart (which
provides read-only file access to the video storage).

PeerTube publishes no Helm chart. The reference deployment is upstream's
Docker setup, `support/docker/production/` (see *Upstream references*); the
chart translates it.

## What it deploys

| Component                        | Object(s)                                                                                                       |
|----------------------------------|-----------------------------------------------------------------------------------------------------------------|
| PeerTube (web, API, job workers) | Deployment `<release>-peertube` (+ SSH sidecar), init container `setup`; Service `:9000`                       |
| PostgreSQL 17                    | StatefulSet `<release>-postgres` + PVC `postgres-data` + Service `:5432`                                        |
| Redis 8 (job queues, sessions)   | StatefulSet `<release>-redis` + PVC `redis-data` + Service `:6379`                                              |
| Files                            | PVC `data` (plan-sized): `data/` at `/data` (videos, thumbnails, plugins, logs), `config/` at `/config`         |
| Credentials                      | Secret `<release>-peertube` (database, `PEERTUBE_SECRET`), Secret `<release>-admin` (standalone installs only)   |
| Ingress                          | `<release>-ingress`, every path to PeerTube                                                                     |
| File access                      | Service `<release>-ssh` only (`ssh-sidecar`); session rooted at `volume:/data`, the volume's `data/` only       |

The images are upstream's own: `chocobozzz/peertube`, and the `postgres` and
`redis` majors upstream's compose file runs. Upstream rebuilds a version's tag
after release, so the catalog pins it with a digest.

Every pod sets `hostUsers: false` and prefers the `nodePool` the catalog
names, as Discourse, App Studio and `custom` do.

Deviations from upstream's packaging, each forced by the platform:

- **No nginx, certbot, webserver-reloader or postfix.** Traefik terminates TLS
  and routes every path to PeerTube, which serves its client, static files
  and websockets itself; upstream's nginx adds caching, rate limiting on
  static files and body limits, none of which PeerTube needs to work. Mail
  goes to the platform's relay (`smtp`), as the other products' does.
- **No live streaming.** PeerTube ingests lives over RTMP on port 1935, which
  has no route into the cluster. `PEERTUBE_LIVE_ENABLED` and
  `PEERTUBE_LIVE_RTMP_ENABLED` are pinned to `false`.
- **The administrator's password is set by `setup`, not by
  `PT_INITIAL_ROOT_PASSWORD`.** PeerTube writes the password of the `root`
  account it creates on first start to its log, which would leave the
  tenant's password in the platform's log store and in `data/logs`. On the
  first start only, `setup` runs PeerTube with its output and log files
  discarded until it answers, stops it, and sets the password with upstream's
  `dist/scripts/reset-password.js`, which reads it from stdin. A marker in
  `/config` makes every later start skip this.
- **One volume for `/data` and `/config`**, as two subdirectories, where
  upstream bind-mounts two host directories. `/config` holds
  `local-production.json`, the settings the admin UI saves.

`PEERTUBE_SECRET` is generated once (64 hex digits, as upstream's
`openssl rand -hex 32`) and read back from `<release>-peertube` on every
later render.

## The owner account

PeerTube is multi-user with roles; the deployment's owner is its `root`
administrator. They sign in with their Freepod account's email
(`caelus.owner.email`, which is also `PEERTUBE_ADMIN_EMAIL`, the root
account's email and the instance's contact address) and the password from
the deploy dialog, `PEERTUBE_ADMIN_PASSWORD`, a required sensitive runtime
var. The `values_schema` mirrors PeerTube's password rules (8 to 50
characters); PeerTube's 72-byte bcrypt limit cannot be expressed there, and a
password beyond it fails `setup` with `New password is invalid.`

PeerTube suggests creating a separate account for publishing rather than
uploading as `root`; that is left to the tenant.

A standalone `helm install` has no vars Secret, so the chart falls back to a
generated password in `<release>-admin`, emitted only in that case.

## What the tenant can change

Environment variables outrank what the admin UI saves: node-config reads
`custom-environment-variables.yaml` after `local-production.json`. Every
`PEERTUBE_*` variable the chart sets is therefore pinned: the hostname, the
database, Redis, mail, the admin email, live streaming and the transcoding
`threads` and `concurrency`. The admin UI still offers the pinned settings
and accepts a change, which then has no effect; upstream has no way to hide a
single setting (`webadmin.configuration.edition.allowed` locks all of them).

Left in the tenant's hands, none of which affects the deployment's integrity:

- **Plugins and themes.** The admin can install any npm package as a plugin,
  which runs inside the PeerTube process. That is the tenant running code in
  their own pod, subject to the tenant network policy.
- **Transcoding resolutions, video imports by URL, automatic transcription,
  remote runners and object storage.** Imports download `yt-dlp` and
  transcription installs `whisper-ctranslate2` with pip into `data/bin`;
  both work, and both use the plan's storage and the pod's memory limit.
- **Sign-ups, quotas, federation and moderation.**

## Manual install

```bash
helm dependency build products/peertube/chart
helm upgrade --install peertube products/peertube/chart \
  --namespace peertube --create-namespace \
  --set host=videos.example.com \
  --set admin.email=me@example.com \
  --set admin.password='choose-a-good-one'
```

## Build and publish

Published to `oci://ghcr.io/erikvanzijst/freepod/charts/peertube` by
[`scripts/publish-charts.sh`](../../scripts/publish-charts.sh), which CI runs on
every merge to `master`: bump `version` in `chart/Chart.yaml` and that version
is published. To publish by hand, from the repository root:

```bash
./scripts/publish-charts.sh peertube
```

| Field               | Value                                                                    |
|---------------------|--------------------------------------------------------------------------|
| Chart ref           | `oci://ghcr.io/erikvanzijst/freepod/charts/peertube`                     |
| User values schema  | see [`products/catalog/peertube/peertube.yaml`](../catalog/peertube/peertube.yaml) |
| Default Helm values | see [`products/catalog/peertube/peertube.yaml`](../catalog/peertube/peertube.yaml) |

## Upstream references

What a version upgrade has to review beyond the tag in
[`products/catalog/peertube/peertube.yaml`](../catalog/peertube/peertube.yaml),
whose `upstream` block detects new releases.

- **Release notes:** GitHub releases of `Chocobozzz/PeerTube` (tags `vX.Y.Z`),
  and `CHANGELOG.md`, whose **IMPORTANT NOTES** section per version lists
  required manual steps and configuration changes.
- **Reference deployment:** `support/docker/production/` in
  `Chocobozzz/PeerTube`: `docker-compose.yml` (the PostgreSQL and Redis
  majors), `.env` (the variables a deployment sets), `Dockerfile` and
  `entrypoint.sh` (the uid 999 `peertube` user, the `gosu` drop, `/data` and
  `/config`), `config/production.yaml` (the storage paths and `trust_proxy`)
  and `config/custom-environment-variables.yaml` (every variable PeerTube
  reads, so every setting the chart can pin).
- **Configuration:** `config/default.yaml`, which documents every setting.
- **First start and password:** `server/core/initializers/installer.ts`
  (`createOAuthAdminIfNotExist`, which logs the root password) and
  `server/scripts/reset-password.ts`, which `setup` runs as
  `dist/scripts/reset-password.js`.

Pitfalls:

- **A PostgreSQL major bump is a dump and restore**, not a tag change.
  Upstream's compose file runs `postgres:17-alpine` and notes that from 18 the
  mount point moves; the chart's `PGDATA` is set explicitly.
- **Check `CHANGELOG.md`'s IMPORTANT NOTES** for manual migration scripts
  (`dist/scripts/migrations/peertube-<version>.js`). PeerTube runs its schema
  migrations itself on start, but some releases also require a script run
  after them while PeerTube is running, which nothing in the chart does: such
  an upgrade has to add a way to run it to every existing deployment. A fresh
  install needs none; `installer.ts` lists the scripts it marks as already run.
- **Check that `installer.ts` still names the administrator `root`** and that
  `reset-password.js` still reads the password from stdin, or a new
  deployment's owner cannot sign in.
- **The `-trixie` tags are aliases** of the plain ones; the catalog's `match`
  excludes them so each version is proposed once.
