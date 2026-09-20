# PhotoPrism — Freepod chart

A self-contained Helm chart for [PhotoPrism](https://www.photoprism.app/), a
self-hosted, AI-powered photo library. The chart renders the entire deployment
directly; its only dependency is Freepod's own `ssh-sidecar` library chart
(which provides read-only file access to the pictures).

## What it deploys

| Component | Object(s) |
|-----------|-----------|
| PhotoPrism (web/API) | Deployment `<release>-photoprism` (+ SSH sidecar, + wait-for-DB init), Service `:2342` |
| MariaDB | Deployment `<release>-mariadb` + PVC `mariadb-data` + Service `:3306` |
| Pictures | PVC `originals` (plan-sized), mounted at `/photoprism/originals` |
| Derived data | PVC `storage`, mounted at `/photoprism/storage` (thumbnails, sidecars, backups, logs) |
| Credentials | Secret `<release>-db` (database), Secret `<release>-admin` (first-start admin password, standalone installs only) |
| Ingress | `<release>-ingress` (per-deployment TLS via `caelus.ingress.tls`) |
| File access | Service `<release>-ssh` only (`ssh-sidecar`); session rooted at `volume:/originals` |

**The database is bundled rather than platform-provided.** PhotoPrism's only
database drivers are SQLite and MySQL/MariaDB, so the platform's relational
storage — which is PostgreSQL — cannot serve this product, and the chart ships
MariaDB itself. The `originals`, `storage` and `mariadb-data` PVCs use fixed
names (not release-prefixed) so an existing volume in the namespace is
re-adopted on upgrade rather than replaced by a fresh, empty one.

**The two data volumes are separate because upstream requires it:** the storage
tree must not live inside `originals`, or PhotoPrism indexes its own
thumbnails. Only `originals` is sized from the plan; `storage` holds derived
data whose footprint tracks thumbnail settings rather than the tenant's
allowance.

## How it runs

The application container runs as uid 1000, which is what upstream's own chart
does. The image's entrypoint runs as root when it can, chowns
`/photoprism/storage`, and then drops to `PHOTOPRISM_UID`; starting as 1000
skips that path entirely, so the volumes are made writable with `fsGroup` and
the pod needs no capability that Pod Security `baseline` would refuse. Note
that `runAsNonRoot` is set on the *container*, never the pod: the SSH sidecar
beside it runs as root, and a pod-level setting would stop the kubelet from
starting that container at all.

Probes use PhotoPrism's own endpoints. `/readyz` reports whether the server
finished initializing — it does not bind its port until schema migrations are
done, which is why the startup budget is 15 minutes. `/healthz` answers without
touching the database or the index, which is what makes it safe to restart on:
it cannot be starved by a long indexing or face-recognition pass.

## The admin password

PhotoPrism applies `PHOTOPRISM_ADMIN_PASSWORD` when the admin account is
created and ignores it afterwards, and it offers no invite flow, so every
deployment needs one from the outset.

The tenant supplies it in the deploy dialog as `PHOTOPRISM_ADMIN_PASSWORD`,
marked `x-caelus-target: runtime`, `x-caelus-sensitive: true` and `required` in
the user values schema — the same treatment as Lemmy's admin password. It is
therefore encrypted at rest, write-only through every API surface, and never
enters Helm values, which are logged in full and persisted by Helm into an
object in the tenant's own namespace.

Requiring it is safe on later edits: vars are validated as the deployment's
**desired** state, so a var the request does not mention is carried forward
from its current value rather than treated as absent. An untouched password
field therefore satisfies `required` without being retyped.

A standalone `helm install` has no vars Secret, so the chart falls back to a
generated password in `<release>-admin`. That Secret is emitted **only** in the
standalone case: under Caelus it would be a second, unused copy of a credential
that is write-only everywhere else.

PhotoPrism reads the value straight from its environment, so unlike Lemmy no
init container is needed to merge it into a config file. The database
credentials are applied after it in `envFrom`, so no var can displace them.

## Manual install

```bash
helm dependency build products/photoprism/chart
helm upgrade --install photoprism products/photoprism/chart \
  --namespace photoprism --create-namespace \
  --set host=photos.example.com \
  --set admin.password=choose-a-good-one
```

`image.tag` defaults to the chart `appVersion`; override it to pin a PhotoPrism
release.

## Build and publish

Published to `oci://ghcr.io/erikvanzijst/freepod/charts/photoprism` by
[`scripts/publish-charts.sh`](../../scripts/publish-charts.sh), which CI runs on
every merge to `master`: bump `version` in `chart/Chart.yaml` and that version
is published. To publish by hand, from the repository root:

```bash
./scripts/publish-charts.sh photoprism
```

The published chart is then referenced from a Caelus product template:

| Field               | Value                                                       |
|---------------------|-------------------------------------------------------------|
| Chart ref           | `oci://ghcr.io/erikvanzijst/freepod/charts/photoprism`      |
| Chart version       | `0.1.0`                                                     |
| User values schema  | see [`products/catalog/photoprism.yaml`](../catalog/photoprism.yaml) |
| Default Helm values | see [`products/catalog/photoprism.yaml`](../catalog/photoprism.yaml) |

## Upstream references

What a version upgrade has to review beyond the tag in
[`products/catalog/photoprism.yaml`](../catalog/photoprism.yaml), whose
`upstream` block detects new releases.

- **Release notes:** GitHub releases of `photoprism/photoprism`, which link the
  fuller entry at `https://docs.photoprism.app/release-notes/`.
- **Reference deployment:** `https://dl.photoprism.app/docker/compose.yaml`.
  **The compose files in the repository are not it** — `compose.yaml`,
  `compose.latest.yaml` and `compose.mariadb.yaml` all say "FOR TEST AND
  DEVELOPMENT ONLY" and describe the contributor environment, including a
  non-default database port and a Traefik with its own certificates.
- **Runtime image:** `docker/photoprism/resolute/Dockerfile` (the production
  stage: `ENV`, `EXPOSE`, `WORKDIR`), plus `scripts/dist/entrypoint.sh` and
  `scripts/dist/entrypoint-init.sh`, which are where the uid switch, the chown
  and `PHOTOPRISM_INIT` actually happen. `docker/README.md` says which base is
  current.
- **Official chart:** `photoprism/photoprism-plus`, published from
  `setup/charts/plus/` and served at `https://charts.photoprism.app/photoprism`;
  its `appVersion` names the release a chart version targets.
- **Images:** one tag drives `docker.io/photoprism/photoprism`. The published
  image is the community edition build — its Dockerfile records
  `DOCKER_IMG=ce` — so the plain dated tag is the one to pin and the `-ce` tags
  are aliases. The `-legacy`, `-jammy`, `-debian` and `armv7` variants are
  unmaintained by upstream's own statement.

Pitfalls:

- **Keep the image tag quoted.** Upstream versions are six-digit dates, so an
  unquoted `tag: 260919` parses as an integer and the chart's values schema
  rejects it. This applies to the catalog file the upgrade tooling edits.
- `PHOTOPRISM_INIT` is emptied on purpose. The image ships `"https"`, which
  installs packages over the network at first start; nothing a pod needs in
  order to boot should be fetched at boot. `PHOTOPRISM_DEFAULT_TLS` is off for
  the same reason — left on, the init step generates a self-signed certificate
  this deployment never serves.
- The MariaDB flags mirror upstream's reference compose (isolation level,
  character set, lock behavior). Only `--innodb-buffer-pool-size` is retuned,
  halved to 256M for density on a shared node; it is the largest single term in
  an idle instance's memory footprint. If upstream moves the MariaDB major
  version, the data directory needs `mariadb-upgrade`, which the chart requests
  with `MARIADB_AUTO_UPGRADE`.
- Database and admin credentials are generated once and then read back from
  their Secrets on every later render. Both seed state that cannot be changed
  afterwards — the MariaDB data directory and the admin account — so a value
  that drifted between releases would lock the deployment out of itself.
- Upstream is explicit that a hard memory limit causes restarts while indexing
  RAW images and panoramas, so the chart sets requests and no memory limit.
  `PHOTOPRISM_WORKERS` is pinned low instead of upstream's `auto`, which would
  give one tenant every core on the node.
