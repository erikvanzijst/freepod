# Lemmy

A self-contained Lemmy chart: it renders the whole instance — the routing proxy,
the Rust backend, the SSR frontend, the pict-rs media server and a bundled
PostgreSQL — on the official upstream images. It has no chart dependencies.

Lemmy publishes no official Helm chart. The community charts that exist
(`dudeami0/lemmy-chart`, `jlh/lemmy-k8s`) describe themselves as experimental, so
this is a bespoke Caelus-native chart in the same style as `nextcloud` and
`immich`, derived from upstream's `lemmy-ansible` production compose.

## What it deploys

| Component  | Object(s)                                                                                                                                                        |
|------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Proxy      | Deployment `<release>-proxy` on `nginx:1.29-alpine` (non-root, read-only rootfs) + Service `:8536`; routing config in ConfigMap `<release>-proxy`                  |
| Backend    | Deployment `<release>-lemmy` on `dessalines/lemmy` (+ render-config and wait-for-DB inits), Service `:8536`; config assembled into an emptyDir at `/config`      |
| Frontend   | Deployment `<release>-lemmy-ui` on `dessalines/lemmy-ui`, Service `:1234`                                                                                          |
| Media      | Deployment `<release>-pictrs` on `asonix/pictrs` (uid 991), Service `:8080`, PVC `<release>-pictrs` (plan-sized) at `/mnt`                                          |
| PostgreSQL | StatefulSet `<release>-postgresql` on `postgres:17-alpine` + headless Service; data on PVC `data-<release>-postgresql-0`; in-memory `/dev/shm`                      |
| Secrets    | Secret `<release>-secrets` — DB credentials, pict-rs API key, and `config.json` (the config minus the admin password)                                              |
| Ingress    | `<release>-ingress` -> the proxy (per-deployment TLS via `caelus.ingress.tls`)                                                                                     |
| File access | Service `<release>-ssh` only (`ssh-sidecar`), sidecar in the pict-rs pod; session rooted at `volume:/media`, read-only                                             |

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
`config.hjson`, so those values must be materialised both where the config is
rendered and where Postgres and pict-rs consume them.

Helm scopes template variables per file. Deriving these across separate templates
would call `randAlphaNum` twice on a first install and hand Lemmy a password
Postgres was never initialised with. Everything generated therefore lives in
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
`deser_hjson` and honours exactly three environment variables —
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

The config is written as **strict JSON**, not hjson. hjson is a JSON superset,
so `deser_hjson` accepts either, and strict JSON buys two things:

1. `secrets.yaml` builds the config as a Helm **dict** and serialises it with
   `toPrettyJson`. Nothing is hand-quoted, so a hostname, site name or SMTP
   login containing a `"` or `\` is escaped by the serialiser rather than by
   whoever edits the template next.
2. The rendered result is a complete, valid document, so `render-config` can
   **merge into it structurally** instead of splicing text:

```js
const cfg = JSON.parse(fs.readFileSync("/config-src/config.json", "utf8"));
cfg.setup.admin_password = pw;
fs.writeFileSync("/config/config.hjson", JSON.stringify(cfg, null, 2));
```

`JSON.stringify` escapes the password by construction — quotes, backslashes,
newlines and non-ASCII all survive, and none of them can corrupt the document.
There is no hand-rolled escaping on this path at all.

This is deliberately *not* `envsubst` or `sed`. Those are pure textual
substitution with no escaping whatsoever: a password containing a double quote
would terminate the JSON string early and produce a config Lemmy refuses to
parse — turning a legal password into a failed deployment. Shell-side escaping
(`sed 's/"/\\"/g'` and friends) can be made correct, but it is correct only as
long as nobody edits it, which is a poor property for the one line standing
between a tenant's password and a broken instance.

`render-config` reuses the **frontend** image: the release already pulls it, its
tag already moves in lockstep with the backend's, and all this needs is a JSON
parser — which the Postgres image does not have. It exits non-zero when the
password is unset or empty, so a misconfigured release stops at `Init:Error`
rather than booting an instance with a blank admin credential.

The schemas additionally reject control characters in both the password and the
site name. That is an input-domain restriction, not a safety mechanism — the
escaping above is what makes the path safe — but a newline in an instance name
is meaningless, and narrowing the domain keeps the failure modes boring.

A standalone `helm install` has no vars Secret, so the chart falls back to a
generated password in `<release>-secrets` under `admin-password`. That key is
emitted **only** in the standalone case: under Caelus it would be a second,
unused copy of a credential that is write-only everywhere else.

Note what this does *not* buy: the password still lands in Postgres as a bcrypt
hash, which is exactly where a password belongs, and `setup` is consumed only on
first boot. Changing the var later does not change the password on an
initialised instance.

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
  `siteName` on an initialised instance does nothing; use the admin UI.
- **Backend and frontend versions move together.** `ui.image.tag` falls back to
  the same `appVersion` as the backend, because lemmy-ui is only supported
  against its matching backend release.
- **Postgres is the stock image, not `pgautoupgrade`.** Upstream ships
  pgautoupgrade so a major bump migrates itself on restart; this chart matches
  the other Caelus charts instead — the operator pins the tag, and a major
  version bump is a deliberate dump/restore.
- **`postgresql.enabled: false` requires `postgresql.host`.** The flag alone
  would leave the config pointing at a Service the release never creates; set
  the host to an external Postgres alongside it.
- **File access exposes the media volume only** — see below.

The platform's tenant NetworkPolicy already accommodates this chart: it allows
free traffic within the namespace (proxy → backend → Postgres/pict-rs) and public
egress, which federation requires.

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

The published chart is then referenced from a Caelus product template:

| Field               | Value                                             |
|---------------------|---------------------------------------------------|
| Chart ref           | `oci://ghcr.io/erikvanzijst/freepod/charts/lemmy` |
| Chart version       | `0.5.1`                                           |
| User values schema  | `chart/user.schema.json` (see below)              |
| Default Helm values | `chart/default_values.json` (see below)           |

## User values schema

`chart/user.schema.json` defines the form fields on the user-facing deployment
dialog. `host` and `siteName` are chart values; `LEMMY_ADMIN_PASSWORD` is routed
to the pod environment and marked sensitive, so it is encrypted, write-only, and
kept out of Helm values entirely. All three are required.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "host": {
      "type": "string",
      "title": "Hostname",
      "minLength": 1,
      "maxLength": 253,
      "description": "The fully qualified domain name for your instance (e.g. lemmy.freepod.eu). Federation bakes this into every user and community address, so it cannot be changed later without losing your identity on the network."
    },
    "siteName": {
      "type": "string",
      "title": "Instance name",
      "minLength": 1,
      "maxLength": 20,
      "description": "The name shown in the header and to other instances. Maximum 20 characters. You can change this later from the admin settings.",
      "pattern": "^[^\\u0000-\\u001f\\u007f]+$"
    },
    "LEMMY_ADMIN_PASSWORD": {
      "type": "string",
      "title": "Admin password",
      "minLength": 10,
      "maxLength": 60,
      "pattern": "^[^\\u0000-\\u001f\\u007f]+$",
      "x-caelus-target": "runtime",
      "x-caelus-sensitive": true,
      "description": "Password for the initial admin account (username 'admin'). Between 10 and 60 characters. Store it somewhere safe: it is write-only, so nobody — can read it back. It seeds the account on first start only; to change it later, use Lemmy's own settings page."
    }
  },
  "required": [
    "host",
    "siteName",
    "LEMMY_ADMIN_PASSWORD"
  ]
}
```

Everything else (images, storage sizing, DB credentials, SMTP, TLS) is operator-
or plan-controlled and is not exposed.

## Default values (system_values_json)

`chart/default_values.json` is the static default-values blob the admin sets on
the product template. It is merged over the chart's `values.yaml` for every
deployment created from that template, and is where operator-wide settings live —
SMTP, the admin username, and pinned image tags. It is not where per-tenant
values (`host`, `siteName`), the tenant-supplied admin password, plan-injected
values (storage sizing), or the generated credentials go.

```json
{
  "image": { "tag": "0.19.20" },
  "ui": { "image": { "tag": "0.19.20" } },
  "admin": { "username": "admin" },
  "smtp": {
    "host": "smtp.mailer.svc.cluster.local",
    "port": 25,
    "fromAddress": "noreply@freepod.eu",
    "tlsType": "none"
  }
}
```

Pin both image tags together. Leave `smtp.host` empty to disable mail.

## Verification performed

The chart was rendered and exercised against the real upstream images before
being committed:

- `helm lint` clean; `helm template` renders 14 objects, all of which pass
  `kubeconform -strict` against the Kubernetes 1.31 schemas. (This caught a
  duplicate `app.kubernetes.io/instance` key in the workload label blocks, now
  fixed via a dedicated `lemmy.componentLabels` helper.)
- The generated DB password, pict-rs API key and admin password were asserted
  identical between `config.hjson` and their discrete Secret keys — the failure
  mode the single-file derivation exists to prevent.
- `nginx -t` passes on the rendered config, running as uid 101 with a read-only
  root filesystem.
- All 19 routing cases (browser, ActivityPub `Accept`, every non-GET verb, each
  backend path prefix, `security.txt`) were asserted against the rendered proxy
  config with stand-in upstreams.
- Both credential paths were rendered and validated: with a vars Secret (no
  `admin-password` key emitted anywhere) and standalone (generated fallback).
  The password's *value* appears in no rendered object on either path.
- The projection logic was run against the real `template_values` service: the
  chart projection carries only `host`/`siteName`, the vars projection only the
  sensitive password. Submitting the password as a chart value, omitting it,
  sending one under 10 characters, or one containing a newline are all rejected,
  and no error message echoes the value.
- Strict JSON was confirmed acceptable to Lemmy 0.19.20 as a config file before
  the format was adopted, hostile values included.
- The merge was exercised end to end with a password of ``p$a"b\c`d{}12`` and a
  site name of `He said "hi" \ bye`: real Lemmy booted on the merged config,
  authenticated the admin, and reported the site name back byte-for-byte.
  `render-config` exits 1 on an unset or empty password.
- emptyDir writability was checked **on the dev cluster**, not just in Docker: a
  pod running the frontend image as its own non-root user writes the file and
  the backend image reads it (both uid 1000, file mode 0644).
- File access was exercised end to end on the dev cluster in a PSA `baseline`
  namespace: both containers reach Ready, a real pict-rs upload lands on the
  volume, the release-name user logs in, `ls` works, and the downloaded blob is
  byte-identical to what was uploaded. `put`, `mkdir` and `rm` are all refused
  by the read-only mount, and the volume is unchanged afterwards.
- Reconciler injection was rendered both ways: wildcard TLS (no `tls` block, no
  issuer annotation) and a custom domain (cert-manager issuer + `tls` block),
  and `caelus.plan.storageSize` was confirmed to size the pict-rs PVC while the
  database PVC stays at its operator-set size.
- The full five-container stack was booted on the real images: Lemmy 0.19.20
  accepted the rendered `config.hjson`, migrated the database, served
  `/.well-known/nodeinfo` and the ActivityPub instance actor with correct
  `https://` URLs; the seeded admin logged in with the generated password; and a
  PNG upload succeeded through proxy → backend → pict-rs, exercising the shared
  API key.
