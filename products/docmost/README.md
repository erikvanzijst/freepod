# Docmost — Freepod chart

A self-contained Helm chart for [Docmost](https://docmost.com/), a
collaborative wiki with real-time editing. The chart renders the entire
deployment directly; its only dependency is Freepod's own `ssh-sidecar`
library chart (which provides read-only file access to the stored files).

## What it deploys

| Component | Object(s) |
|-----------|-----------|
| Docmost (web, API and collaboration WebSocket on one port) | Deployment `<release>-docmost` (+ SSH sidecar, + wait-for-Postgres init), Service `:3000` |
| PostgreSQL | StatefulSet `<release>-postgres` + PVC `postgres-data` + Service `:5432` |
| Redis (job queues, collaboration fan-out) | StatefulSet `<release>-redis` + PVC `redis-data` + Service `:6379` |
| Files | PVC `storage` (plan-sized) at `/app/data/storage` (`STORAGE_DRIVER=local`) |
| Credentials | Secret `<release>-db` (database, `APP_SECRET`), Secret `<release>-admin` (first-start owner password, standalone installs only) |
| Ingress | `<release>-ingress` (per-deployment TLS via `caelus.ingress.tls`) |
| File access | Service `<release>-ssh` only (`ssh-sidecar`); session rooted at `volume:/storage` |

The image is upstream's own `docmost/docmost`: it runs as `node` (uid 1000),
serves one Node process on 3000, and migrates the database at start. PostgreSQL
and Redis are bundled at the tags upstream's reference compose runs, Redis with
the same `appendonly` and `noeviction` settings, which its job queues need.

`APP_SECRET` is generated once and read back from `<release>-db` on every
later render: it signs sessions and keys Docmost's encryption of stored
secrets, so a key that changed would sign everyone out and strand those
secrets.

## The owner account

Docmost is multi-user, but every account belongs to one workspace, with
spaces and roles on top. A deployment therefore has one owner, and the tenant
is that owner: they sign in with their Freepod account's email
(`caelus.owner.email`) and the deploy dialog asks only for a display name
(`admin.name`) and a password.

The password is `DOCMOST_ADMIN_PASSWORD`, a required sensitive runtime var,
the same treatment as BookStack's and PhotoPrism's admin passwords. Docmost
itself never reads it. Docmost has no command to seed an account; a fresh
instance instead offers its first-run setup (`POST /api/auth/setup`) to whoever
reaches it first. The application container's `postStart` hook calls it over
localhost once `/api/health` answers, and treats the 403 that setup returns once
a workspace exists as success, so later starts change nothing. Kubernetes runs
no probe until the hook completes, so the pod is not Ready, and the ingress has
no endpoint, until the owner exists: the setup page is never reachable from
outside on a fresh install. A failing hook restarts the container, which
retries it.

The workspace is created as "My workspace"; the owner renames it in Docmost's
settings.

A standalone `helm install` has no vars Secret, so the chart falls back to a
generated password in `<release>-admin`, emitted only in that case.

## Manual install

```bash
helm dependency build products/docmost/chart
helm upgrade --install docmost products/docmost/chart \
  --namespace docmost --create-namespace \
  --set host=wiki.example.com \
  --set admin.email=me@example.com \
  --set admin.password=choose-a-good-one
```

## Build and publish

Published to `oci://ghcr.io/erikvanzijst/freepod/charts/docmost` by
[`scripts/publish-charts.sh`](../../scripts/publish-charts.sh), which CI runs on
every merge to `master`: bump `version` in `chart/Chart.yaml` and that version
is published. To publish by hand, from the repository root:

```bash
./scripts/publish-charts.sh docmost
```

| Field               | Value                                                              |
|---------------------|--------------------------------------------------------------------|
| Chart ref           | `oci://ghcr.io/erikvanzijst/freepod/charts/docmost`                |
| Chart version       | `0.1.2`                                                            |
| User values schema  | see [`products/catalog/docmost/docmost.yaml`](../catalog/docmost/docmost.yaml) |
| Default Helm values | see [`products/catalog/docmost/docmost.yaml`](../catalog/docmost/docmost.yaml) |

## Upstream references

What a version upgrade has to review beyond the tag in
[`products/catalog/docmost/docmost.yaml`](../catalog/docmost/docmost.yaml), whose
`upstream` block detects new releases.

- **Release notes:** the GitHub releases of `docmost/docmost`. Each lists
  highlights, a separate **Enterprise** section, and security notes.
- **Reference deployment:** `docker-compose.yml` in `docmost/docmost`.
  **The `postgres` and `redis` tags there are the ones `postgres.image.tag` and
  `redis.image.tag` track**, as are Redis's `command` arguments.
- **Runtime image:** `Dockerfile` in `docmost/docmost`: the uid, the port, and
  the storage path (`/app/data/storage`).
- **Application configuration:** `.env.example` lists the documented
  environment options; `apps/server/src/integrations/environment/environment.service.ts`
  lists every one the server reads, including undocumented ones.
- **Owner seeding:** `apps/server/src/core/auth/dto/create-admin-user.dto.ts`
  (the setup payload and its limits, which the catalog's `values_schema`
  mirrors) and `guards/setup.guard.ts` (the 403 once a workspace exists).

Pitfalls:

- **Never set `CLOUD=true`.** It switches Docmost to its hosted multi-workspace
  mode, and in that mode the license check passes unconditionally: every
  Enterprise feature unlocks without a license. The image ships the Enterprise
  code (under the Docmost Enterprise License) and gates it on a license key the
  tenant may buy and enter themselves.
- **Enterprise features are not ours to advertise.** The open-source edition
  lacks, among others, 2FA, SSO, page-level permissions, API keys, templates,
  personal spaces and resolving comments; the settings UI shows them, locked.
  Check the release's Enterprise section before adding a listing feature.
- **The setup contract is load-bearing.** The `postStart` hook relies on
  `POST /api/auth/setup` answering 403 once a workspace exists. If upstream
  changes that status or the payload, first starts fail or, worse, the hook
  stops recognizing a configured instance.
- **PostgreSQL 18 keeps PGDATA in a versioned subdirectory** of
  `/var/lib/postgresql`, which is where `postgres-data` is mounted. A major
  bump is a dump and restore, not a tag change.
- **`ALLOWED_PRIVATE_NETWORKS` stays `none`.** It keeps server-side fetches
  (link previews, embeds) off private addresses, which here are the cluster's
  own services.
