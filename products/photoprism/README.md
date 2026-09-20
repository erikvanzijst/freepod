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

The container starts as **root**, and that is required rather than preferred:
the image's PID 1 is s6-overlay (`ENTRYPOINT ["/init"]`), which prepares `/run`
before handing off and exits when it cannot. A pod-level `runAsUser: 1000`
produces a container that fails to start, not one that runs unprivileged.

Unprivileged operation is configured through the image instead.
`PHOTOPRISM_UID`/`PHOTOPRISM_GID` are set to 1000, so the entrypoint performs
the setup that needs root, chowns `/photoprism/storage`, and then `setpriv`s
the application down to that uid. Capabilities are deliberately not dropped:
that chown and that uid switch need CHOWN, SETUID and SETGID, which are in the
default set and so ask nothing of Pod Security `baseline`. `fsGroup: 1000`
covers `originals`, which the entrypoint does not chown.

Probes use PhotoPrism's own endpoints. `/readyz` reports whether the server
finished initializing — it does not bind its port until schema migrations are
done, which is why the startup budget is 15 minutes. `/healthz` answers without
touching the database or the index, which is what makes it safe to restart on:
it cannot be starved by a long indexing or face-recognition pass.

## The admin password

PhotoPrism is multi-user, but every account shares one library: roles (admin,
user, viewer, guest) differ in permissions, not in owning separate collections.
A deployment therefore has exactly one owner, and the tenant *is* that owner —
so the deploy dialog asks for their own **Username** and **Password** rather
than for an "admin password". They can invite others afterwards from
PhotoPrism's own settings.

Both are applied when the account is created on first start and ignored after
that, and PhotoPrism offers no invite flow, so both are required from the
outset.

They travel by different channels, which is invisible in the dialog but matters
here. The username is an ordinary chart value (`admin.username`), because it
reaches the pod as `PHOTOPRISM_ADMIN_USER` and is not a secret. The password is
`PHOTOPRISM_ADMIN_PASSWORD`, marked `x-caelus-target: runtime`,
`x-caelus-sensitive: true` and `required` — the same treatment as Lemmy's admin
password — so it is encrypted at rest, write-only through every API surface,
and never enters Helm values, which are logged in full and persisted by Helm
into an object in the tenant's own namespace.

Neither can be changed by editing the deployment later: the template's
`system_values` still carry `admin.username: admin` as a fallback, and a
tenant's value overrides it, but PhotoPrism itself only reads either one when
it creates the account.

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
| Chart version       | `0.1.2`                                                     |
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

- **Never set `runAsUser` on the application container, and do not drop its
  capabilities.** PID 1 is s6-overlay, which needs root to prepare `/run`;
  starting as a non-root uid fails with `/run belongs to uid 0 instead of
  <uid> … we're lacking the privileges to fix it`, and dropping CHOWN/SETUID/
  SETGID breaks the same startup path. The uid the application ends up running
  as is `PHOTOPRISM_UID`, never the pod security context.
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
