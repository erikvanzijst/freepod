# Lemmy

A self-contained Lemmy chart: it renders the whole instance — the routing proxy,
the Rust backend, the SSR frontend, the pict-rs media server and a bundled
PostgreSQL — on the official upstream images. Its only chart dependency is the
platform's own `ssh-sidecar` library chart (see *File access*).

Lemmy publishes no official Helm chart. The community charts that exist
(`dudeami0/lemmy-chart`, `jlh/lemmy-k8s`) describe themselves as experimental, so
this is a bespoke Caelus-native chart in the same style as `nextcloud` and
`immich`, modeled on the reference deployment in Lemmy's Docker install guide:
the compose file from `lemmy-docs`, and the config and nginx routing from
`lemmy-ansible` (see *Upstream references*).

## What it deploys

| Component   | Object(s)                                                                                                                                                   |
|-------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Proxy       | Deployment `<release>-proxy` on `nginx:1.29-alpine` (non-root, read-only rootfs) + Service `:8536`; routing config in ConfigMap `<release>-proxy`           |
| Backend     | Deployment `<release>-lemmy` on `dessalines/lemmy` (+ render-config and wait-for-DB inits), Service `:8536`; config assembled into an emptyDir at `/config` |
| Frontend    | Deployment `<release>-lemmy-ui` on `dessalines/lemmy-ui`, Service `:1234`                                                                                   |
| Media       | Deployment `<release>-pictrs` on `asonix/pictrs` (uid 991), Service `:8080`, PVC `<release>-pictrs` (plan-sized) at `/mnt`                                  |
| PostgreSQL  | StatefulSet `<release>-postgresql` on `postgres:17-alpine` + headless Service; data on PVC `data-<release>-postgresql-0`; in-memory `/dev/shm`              |
| Secrets     | Secret `<release>-secrets` — DB credentials, pict-rs API key, and `config.json` (the config minus the admin password)                                       |
| Ingress     | `<release>-ingress` -> the proxy (per-deployment TLS via `caelus.ingress.tls`)                                                                              |
| File access | Service `<release>-ssh` only (`ssh-sidecar`), sidecar in the pict-rs pod; session rooted at `volume:/media`, read-only                                      |

Five workloads, one replica each: the backend's federation workers and pict-rs's
sled index both assume a single writer, so nothing here scales horizontally.

## Why there is an nginx in the release

This is the part of a Lemmy deployment that does not survive being simplified.
Lemmy serves one hostname from two processes, and the split is not by path alone:

- `GET`/`HEAD` carrying an ActivityPub or JSON-LD `Accept` header → **backend**.
  This is how remote instances resolve actors and objects. Route it to the
  frontend and federation breaks *silently* — browsers see a perfectly healthy
  site while no other instance can talk to yours.
- Any non-`GET`/`HEAD` request → **backend** (logins, votes, inbox deliveries).
- `/api`, `/pictrs`, `/feeds`, `/nodeinfo`, `/version`, `/sitemap.xml`,
  `/.well-known` → **backend**, by path. Except `/.well-known/security.txt`,
  which the frontend owns.
- Everything else → **frontend**.

A Kubernetes Ingress can express the path rules and nothing else. The header- and
verb-based rules need a real proxy, so the chart ships upstream's `map` from
`lemmy-ansible`'s `nginx_internal.conf`, retargeted at Services. The Ingress has
a single `/` rule pointing at it.

One deliberate change from upstream: `absolute_redirect off`. TLS terminates at
the edge, so nginx only ever sees plain HTTP and would emit the trailing-slash
redirect as an absolute `http://` URL, bouncing browsers out of TLS. A relative
`Location` resolves against whatever origin the browser is already on.

## Secrets are generated in one file, on purpose

Lemmy takes the database password and the pict-rs API key as *literals* inside
`config.hjson`, so those values must be materialized both where the config is
rendered and where Postgres and pict-rs consume them.

Helm scopes template variables per file. Deriving these across separate templates
would call `randAlphaNum` twice on a first install and hand Lemmy a password
Postgres was never initialized with. Everything generated therefore lives in
`templates/secrets.yaml`, computed once and reused. Consumers read discrete keys
with `secretKeyRef` rather than `envFrom`, because the Secret also carries a
config key — not a valid environment variable name, and enough to put a whole
pod into `InvalidVariableNames`.

Each value is generated on first install and then read back from the Secret via
`lookup` on every upgrade, so a live credential never rotates underneath a
running instance. Set `postgresql.auth.password` or `pictrs.apiKey` to pin
explicit values instead.

## The admin password is a runtime var, not a chart value

The tenant supplies it in the deploy dialog as `LEMMY_ADMIN_PASSWORD`, marked
`x-caelus-target: runtime` and `x-caelus-sensitive: true` in the user values
schema, and `required`. It is therefore encrypted at rest, write-only through
every API surface, and — the point of the exercise — **never enters Helm
values**, which are logged in full at INFO and persisted by Helm into an object
in the tenant's own namespace.

Getting there takes one extra step, because Lemmy cannot read it from the
environment. `crates/utils/src/settings/mod.rs` parses its config with
`deser_hjson` and honors exactly three environment variables:
`LEMMY_DATABASE_URL`, `LEMMY_CONFIG_LOCATION` and
`LEMMY_INITIALIZE_WITH_DEFAULT_SETTINGS`. There is no generic override, and
nothing at all for `setup.admin_password`. The value has to reach Lemmy inside
the file.

So the chart merges it in at pod start:

```
Secret <release>-secrets          per-release vars Secret (platform-owned)
  config.json                       LEMMY_ADMIN_PASSWORD
        |                                   |
        +----------> render-config <--------+     (init container)
                          |
                    emptyDir /config/config.hjson
                          |
                      lemmy container
```

### Why there is no string templating anywhere on this path

The config is **strict JSON**, which `deser_hjson` accepts because hjson is a
superset. `secrets.yaml` builds it as a Helm dict and serializes it with
`toPrettyJson`, so hostnames, site names and SMTP logins are escaped by the
serializer, not by hand. `render-config` then parses that document, sets
`setup.admin_password`, and writes it back with `JSON.stringify` (see
`templates/lemmy.yaml`), so no password can corrupt it. `envsubst` or `sed`
would break on the first password containing a `"`.

The schemas also reject control characters in the password and site name. That
narrows the input domain; the escaping is what makes the path safe.

A standalone `helm install` has no vars Secret, so the chart generates the
password into `<release>-secrets` under `admin-password`. It emits that key only
then: under Caelus it would be an extra copy of a write-only credential.

## Things worth knowing before deploying

- **`host` is permanent.** Lemmy bakes it into every actor URL (`https://<host>/u/alice`)
  and signs federated activities against it. Changing it after the instance has
  federated abandons the old identity — every remote follow, community and
  subscription is orphaned. Treat it as immutable, not as a setting.
- **The plan quota sizes the media volume**, not the database. `caelus.plan.storageSize`
  is applied to the pict-rs PVC, which is what actually grows with tenant
  activity. The Postgres PVC stays operator-sized via `postgresql.persistence.size`.
- **`/dev/shm` is raised to 256Mi.** The 64Mi Kubernetes default provokes
  "could not resize shared memory segment" under Lemmy's parallel queries.
  Upstream sets `shm_size: 2g` on large instances; `postgresql.shmSize` tunes it,
  and it counts against the pod's memory.
- **`siteName` is capped at 20 characters** by Lemmy itself, and the admin
  password must be 10–60. Both are enforced in the schemas.
- **`setup` only applies on first boot.** Changing the admin password var or
  `siteName` on an initialized instance does nothing; use the admin UI.
- **Backend and frontend versions move together.** `ui.image.tag` falls back to
  the backend's resolved tag, because lemmy-ui is only supported against its
  matching backend release. The catalog therefore pins `image.tag` alone.
- **Postgres is the stock image, not `pgautoupgrade`.** Upstream ships
  pgautoupgrade so a major bump migrates itself on restart; this chart matches
  the other Caelus charts instead — the operator pins the tag, and a major
  version bump is a deliberate dump/restore.
- **`postgresql.enabled: false` requires `postgresql.host`.** The flag alone
  would leave the config pointing at a Service the release never creates; set
  the host to an external Postgres alongside it.
- **File access exposes the media volume only** — see below.

## File access

The platform's SSH sidecar, rooted at a read-only mount of the pict-rs media
volume. It rides in the **pict-rs** pod because an RWO PVC can only be shared
between containers of one pod, and pict-rs is what mounts the volume. Spec:
[ssh-chart-contract](../../openspec/specs/ssh-chart-contract/spec.md).

### What a client actually sees

The whole volume, at `/media`:

```
/media/files/01/a0/33/db/1e/9a/77/10/94/e2/60039c1f4605.png
/media/sled-repo/v0.5.0/{conf,db}
```

Both halves are exposed on purpose. `files/` alone is unusable — the sled repo
is what maps aliases to those hashes — so together they are a restorable copy of
pict-rs state, while either alone is not. The volume carries no credentials: the
pict-rs API key arrives by environment.

The copy is only as consistent as the moment it was taken. sled is live while
the instance runs, so treat a pull as crash-consistent, not as a coordinated
backup.

## Manual install

```bash
helm upgrade --install lemmy products/lemmy/chart \
  --namespace lemmy --create-namespace \
  --set host=lemmy.example.com \
  --set siteName="Example"
```

`image.tag` and `ui.image.tag` default to `<appVersion>`. Set `smtp.*` for a real
deployment; leave `smtp.host` empty to disable mail, which also disables email
verification and password resets.

Verify federation is routed correctly — this is the check that catches a broken
proxy, and the one a browser will never fail for you:

```bash
# must return JSON from the backend, not HTML from the frontend
curl -H 'Accept: application/activity+json' https://lemmy.example.com/
```

## Build and publish

Published to `oci://ghcr.io/erikvanzijst/freepod/charts/lemmy` by
[`scripts/publish-charts.sh`](../../scripts/publish-charts.sh), which CI runs on
every merge to `master`: bump `version` in `chart/Chart.yaml` and that version
is published. To publish by hand, from the repository root:

```bash
./scripts/publish-charts.sh lemmy
```

## Product definition

Curated: the chart reference, the pinned Lemmy version, the operator-wide
values (SMTP, admin username) and the tenant-facing values schema are all
declared in [`products/catalog/lemmy.yaml`](../catalog/lemmy.yaml). The schema
routes `LEMMY_ADMIN_PASSWORD` to the pod as a sensitive runtime var, as
described above. Format:
[product-catalog-format](../../openspec/specs/product-catalog-format/spec.md).

## Upstream references

What a version upgrade has to review beyond the tag in
[`products/catalog/lemmy.yaml`](../catalog/lemmy.yaml), whose `upstream` block
detects new releases on the backend image. That one tag drives both
`dessalines/lemmy` and `dessalines/lemmy-ui`, so check that both exist.

- **Release notes:** GitHub releases of `LemmyNet/lemmy` (tags have no `v`
  prefix) are one-line pointers to a post on `join-lemmy.org/news`; follow them.
  The posts' sources are in `LemmyNet/joinlemmy-site`, `src/assets/news/`.
- **No official chart.** The reference deployment is the one the Docker install
  guide (`join-lemmy.org/docs/administration/install_docker.html`) downloads:
  - `LemmyNet/lemmy-docs` `assets/docker-compose.yml`. The repo has no tags;
    Renovate bumps each image in its own commit, so diff between the commits
    that set `dessalines/lemmy` to the current and target versions
    (`git log -- assets/docker-compose.yml`).
  - `LemmyNet/lemmy-ansible` `examples/config.hjson`,
    `templates/nginx_internal.conf` (the routing map our proxy copies) and
    `files/proxy_params`, plus `UPGRADING.md` for majors. It versions itself
    (`1.5.x`) and pins Lemmy in its `VERSION` file, so diff between the commits
    that bumped `VERSION` (`git log -- VERSION`), not between its tags. Its own
    `templates/docker-compose.yml` lags the docs' compose; don't use it.
  - Not `docker/docker-compose.yml` in `LemmyNet/lemmy`: that one builds Lemmy
    from source for development, not production.
- **Images:** the runtime stage of `docker/Dockerfile` in `LemmyNet/lemmy` and
  of `Dockerfile` in `LemmyNet/lemmy-ui`, at the release tags.
- **Settings:** `config/defaults.hjson` in `LemmyNet/lemmy`. Our config is built
  as a dict in `templates/secrets.yaml`, so a new required key lands there.

Pitfalls:

- **1.0 reshapes the config.** It is the next major after 0.19 (there is no
  0.20). As of `1.0.0-beta.2`, `config/defaults.hjson` replaces the `database`
  and `email` blocks with `connection` URLs and drops several `pictrs` keys, all
  of which `templates/secrets.yaml` sets. Expect a chart change, not a tag bump.
- **Postgres differs from upstream on purpose.** The docs' compose runs
  `pgautoupgrade`; this chart pins stock `postgres` (see *Things worth
  knowing*), so a major bump there is a dump/restore, never a tag change.
  Compare majors and escalate when upstream's moves ahead of ours.
- **pict-rs is pinned by the chart**, as in the docs' compose. Mirror its tag
  bumps as chart changes.
- **The compose's postfix relay** isn't deployed here. The platform relays mail
  itself.
