# OpenProject — Freepod chart

A self-contained Helm chart for [OpenProject](https://www.openproject.org/),
project management with work packages, Gantt charts, boards, time tracking,
meetings and collaborative documents. The chart renders the entire deployment
directly; its only dependency is Freepod's own `ssh-sidecar` library chart
(which provides read-only file access to the attachments).

## What it deploys

| Component | Object(s) |
|-----------|-----------|
| OpenProject web (Puma) and background worker (GoodJob) | Deployment `<release>-openproject`: containers `web` and `worker` (+ SSH sidecar), init containers `wait-for-postgres` and `seeder`; Service `:8080` |
| hocuspocus (real-time editing of Documents) | Deployment `<release>-hocuspocus`, Service `:1234`, routed at `/hocuspocus` |
| PostgreSQL | StatefulSet `<release>-postgres` + PVC `postgres-data` + Service `:5432` |
| memcached (Rails cache) | Deployment `<release>-memcached`, Service `:11211`, no volume |
| Files | PVC `assets` (plan-sized) at `/var/openproject/assets` |
| Credentials | Secret `<release>-db` (database, `SECRET_KEY_BASE`, hocuspocus secret), Secret `<release>-admin` (first-start owner password, standalone installs only) |
| Ingress | `<release>-ingress` (per-deployment TLS via `caelus.ingress.tls`) |
| File access | Service `<release>-ssh` only (`ssh-sidecar`); session rooted at `volume:/assets` |

The images are upstream's own: `openproject/openproject:<version>-slim`, which
runs as uid 1000, and `openproject/hocuspocus:<version>`, released under the
same version, so `hocuspocus.image.tag` follows `image.tag` unless pinned.
PostgreSQL is bundled at the major version upstream's compose runs for new
installations.

Deviations from upstream's chart and compose, each forced by the platform:

- **Web and worker share one pod.** Both read and write the attachments, and a
  `local-path` volume lives on one node only; upstream runs them as separate
  Deployments on a `ReadWriteMany` volume.
- **The seeder is an init container**, not a Job per Helm revision. It loads
  the schema or migrates, then seeds, before every start, so the web process
  never serves an unmigrated database.
- **No cron container.** It only fetches incoming email over IMAP, and apps on
  Freepod cannot receive email.
- **No read-only root filesystem.** Upstream's chart needs per-pod ephemeral
  volumes for `/tmp` and `/app/tmp` to run that way; the image itself does not.
- **Puma runs in single mode** (`web.workers: 0`): one process with up to 16
  threads, where upstream forks two workers under a master. That is about
  1 GiB less at idle, which is what a deployment is billed for. OpenProject
  enables Rack::Timeout only with two or more workers, so a stuck request is
  left to the liveness probe.
- **The security badge is off.** It advertises upgrades the tenant cannot
  perform; versions are the platform's.

`SECRET_KEY_BASE` and the hocuspocus secret are generated once and read back
from `<release>-db` on every later render: the first signs sessions and
encrypts stored tokens, the second is shared between OpenProject and
hocuspocus.

## The owner account

OpenProject is multi-user with one administrator who invites everyone else.
The deployment's owner is that administrator. OpenProject's seeder creates it
on the first start only, from `OPENPROJECT_SEED__ADMIN__USER__*`: the login is
always `admin`, the email is `caelus.owner.email`, the name is `admin.name`
(split at the first space into first and last name), and the password is
`OPENPROJECT_ADMIN_PASSWORD`, a required sensitive runtime var. The forced
password change upstream defaults to is off, since the tenant chose the
password. The seeder skips validation, so the catalog's `values_schema`
mirrors OpenProject's default password policy itself.

A standalone `helm install` has no vars Secret, so the chart falls back to a
generated password in `<release>-admin`, emitted only in that case.

## What the tenant can change

A setting OpenProject reads from the environment is read-only in its
administration. The chart pins every setting the deployment depends on that
way: the host name, HTTPS and HSTS, the cache, the hocuspocus URL, and mail
delivery. Every OpenProject process gets the same values through
`openproject.env`.

What stays in the tenant's hands, none of which affects the deployment's
integrity: self-registration, password policy, attachment size limits, OAuth
applications, webhooks, and file storage integrations (Nextcloud). Webhooks and
storages make outbound requests from the worker to addresses the tenant
chooses, subject to the tenant network policy.

## Manual install

```bash
helm dependency build products/openproject/chart
helm upgrade --install openproject products/openproject/chart \
  --namespace openproject --create-namespace \
  --set host=projects.example.com \
  --set admin.email=me@example.com \
  --set admin.password='Choose-a-g00d-one'
```

## Build and publish

Published to `oci://ghcr.io/erikvanzijst/freepod/charts/openproject` by
[`scripts/publish-charts.sh`](../../scripts/publish-charts.sh), which CI runs on
every merge to `master`: bump `version` in `chart/Chart.yaml` and that version
is published. To publish by hand, from the repository root:

```bash
./scripts/publish-charts.sh openproject
```

| Field               | Value                                                              |
|---------------------|--------------------------------------------------------------------|
| Chart ref           | `oci://ghcr.io/erikvanzijst/freepod/charts/openproject`            |
| User values schema  | see [`products/catalog/openproject/openproject.yaml`](../catalog/openproject/openproject.yaml) |
| Default Helm values | see [`products/catalog/openproject/openproject.yaml`](../catalog/openproject/openproject.yaml) |

## Upstream references

What a version upgrade has to review beyond the tag in
[`products/catalog/openproject/openproject.yaml`](../catalog/openproject/openproject.yaml),
whose `upstream` block detects new releases.

- **Release notes:** <https://www.openproject.org/docs/release-notes/>, one
  page per release, with a separate section for Enterprise add-ons. The source
  is `docs/release-notes/` in `opf/openproject`.
- **Reference deployment:** `docker-compose.yml` and `.env.example` in
  `opf/openproject-docker-compose` (the process layout, the hocuspocus tag and
  environment, and **the `POSTGRES_VERSION` that `postgres.image.tag`
  tracks**), and `charts/openproject` in `opf/helm-charts` (probes, the worker
  probe port, security context). The Helm chart's bundled Bitnami PostgreSQL
  lags; follow the compose.
- **Runtime image:** `docker/prod/Dockerfile` in `opf/openproject` (the `slim`
  stage: uid, port, `APP_DATA_PATH`) and the process scripts beside it
  (`web`, `worker`, `seeder`, `migrate`).
- **Application configuration:** `config/constants/settings/definition.rb`
  lists every setting, its default and whether it is writable; the environment
  name is the setting's path under `OPENPROJECT_`, with `__` for an underscore
  inside a name.
- **Owner seeding:** `app/seeders/admin_user_seeder.rb` (login `admin`, name
  split, first start only) and `lib/open_project/passwords.rb` (the rules the
  `values_schema` password pattern mirrors).

Pitfalls:

- **Enterprise features are not ours to advertise.** The image contains them,
  locked without a token: among others the team planner, placeholder users,
  SSO, portfolios, custom themes and full baseline comparison. Check the
  release notes' Enterprise section before adding a listing feature.
- **The `-slim` tag is the only one to track.** The plain tag is the
  all-in-one image with its own PostgreSQL, Apache and memcached.
- **`OPENPROJECT_ADDITIONAL__HOST__NAMES` must include the web Service's
  name.** hocuspocus calls OpenProject over the Service, and OpenProject
  answers a host it does not know with 404.
- **A PostgreSQL major bump is a dump and restore**, not a tag change.
