# custom

A generic chart for a **user-supplied application**. Every other product in this
repo pins its image: `vaultwarden/server:1.37.1` is a platform decision, and the
tenant only picks a hostname and a few settings. Here the tenant picks the image
too — it is whatever they built — and the chart's job is to run it without
letting them run somebody else's.

Unlike the curated products, this one is **database-managed**: there is no
`products/catalog/custom.yaml`, because the build subsystem that feeds it is still
being iterated on and pinning it to a rollout-reconciled catalog file would
freeze decisions that are not settled. The product, template, and plan rows are
seeded by hand — see [Caelus product template](#caelus-product-template) for the
values to paste.

## What it deploys

| Component   | Object(s)                                                                                                      |
|-------------|----------------------------------------------------------------------------------------------------------------|
| Application | Deployment `<release>-app` running the user's image, or the placeholder while none exists                      |
| Service     | `<release>-app` `:80` → the container's `http` port                                                            |
| Ingress     | `<release>-ingress` (per-deployment TLS via `caelus.ingress.tls`), only once the reconciler injects a hostname |

No PVC: an image built from a user's source tree is stateless as far as this
chart is concerned. Persistence, if it is ever offered here, is a separate
decision that should not be smuggled in as a default.

## The image contract

The tenant supplies a single string:

```
image: "{user_id}@{digest}"     # e.g. "5@sha256:4777d0…" — 64 lowercase hex chars
```

That is a real image reference with **the registry host stripped off**: the
repository is the owner's own user id. So composing the pull reference is just a
prefix:

```
{registry}/{user_id}@{digest}
```

`5@sha256:4777d0…` under `registry.home` becomes
`registry.home/5@sha256:4777d0…`. The chart still splits on `@` — but only to
police the two halves, not to reassemble them. Digests and repository paths
cannot contain `@`, so the split is unambiguous.

Withholding the registry host is deliberate, and so is verifying rather than
trusting the `{user_id}` repository. Together they are what make the ownership
assertion below meaningful: a tenant can neither point at an arbitrary registry
nor claim someone else's repository.

**Port: bind `0.0.0.0:$PORT`.** The chart injects `PORT` into the container,
set from the `containerPort` system value (default `8080`), and the Service
targets that same port. The platform hands the app its port rather than the app
being required to know one — Railway's convention, which the Railpack builder
assumes, and what makes zero-config builds work (`process.env.PORT || 3000` and
friends). Because the number is never promised to the image, it stays a
platform-side detail that can change without breaking existing builds.

Stated plainly: **an app that hardcodes a port and ignores `$PORT` will only
work if it happens to match `containerPort`.** That is not a contract we
maintain, and such an image can break when the default moves.

The placeholder image is the one exception — it is ours, and nginx will not
read `$PORT` without templating, so it is pinned to the default and must be
rebuilt if the default ever changes.

## Object storage

Every `custom` deployment gets a **private S3 bucket** on the platform's Garage
instance, provisioned automatically. There is nothing to enable and nothing to
configure: the credentials arrive in the container as environment variables, in
the names an S3 SDK already looks for.

```
AWS_ACCESS_KEY_ID          AWS_ENDPOINT_URL_S3     S3_BUCKET
AWS_SECRET_ACCESS_KEY      AWS_ENDPOINT_URL        BUCKET_NAME
AWS_REGION / AWS_DEFAULT_REGION
```

So in Python this is the whole of it:

```python
import boto3, os
s3 = boto3.client("s3")                    # reads AWS_* from the environment
s3.put_object(Bucket=os.environ["S3_BUCKET"], Key="hello.txt", Body=b"hi")
```

**Presigned URLs work in a browser.** The endpoint is publicly reachable, so a
URL your app signs can be handed straight to an end user, for download or for
upload, and the bytes never pass through your pod. Cross-origin browser uploads
are already permitted — the platform sets the bucket's CORS policy, including
exposing `ETag`, which multipart uploads need.

### Two things to know

**Path-style addressing.** The endpoint serves `…/bucket/key`, not
`bucket.host/key`. Python's boto3 selects this automatically for a custom
endpoint and needs nothing. The JavaScript v3 client does not — it needs one
flag:

```javascript
new S3Client({ forcePathStyle: true })     // endpoint/region come from the env
```

## Database

Every `custom` deployment also gets its **own PostgreSQL database** and a login
role that owns it, provisioned automatically. As with the bucket, there is
nothing to enable and nothing to configure — the credentials arrive as
environment variables:

```
DATABASE_URL                 postgresql://<role>:<password>@<pooler>:6432/<db>
PGHOST  PGPORT  PGUSER  PGPASSWORD  PGDATABASE
```

`DATABASE_URL` covers every ORM; the `PG*` variables are what libpq, `psql` and
`pg_dump` read with no arguments. In Python:

```python
import os, psycopg
with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
    conn.execute("CREATE TABLE IF NOT EXISTS visits (id serial primary key)")
```

### What you can and cannot do with it

You **own** the database: create schemas, tables and indexes, and install
PostgreSQL's trusted extensions (`pgcrypto` and friends).

Session state does not survive between transactions (`SET`, `LISTEN`/`NOTIFY`,
session-level advisory locks).

Three role-level settings are applied and re-applied on every deploy:
`statement_timeout = 30s`, `idle_in_transaction_session_timeout = 60s`, and
`temp_file_limit = 64MB`. The first two you can override per session; the third
you cannot.

### The size allowance, and what happens when you hit it

The plan's `database_bytes` bounds the database. At 80% and 90% the owner is
mailed; at 100% the database goes **read-only** — reads keep working, writes are
refused; at 150% the role stops being able to log in at all. Falling back under
the allowance reverses each step on the next sweep.

### Backups

There are none you can reach. An accidental `DROP TABLE` is not recoverable.
Deleting the deployment revokes access immediately and the data is destroyed
after the platform's retention period.

### How it is wired

Two distinct keys, and the distinction is the same one object storage draws:

- `relationalStorage.enabled` is the **product's** static declaration, set in
  `products/catalog/custom.yaml` under `template.system_values`. It is
  identical for every deployment of this product and a tenant cannot set it.
- `caelus.database.{host,port,name,user,secretName}` are the **per-deployment**
  facts the reconciler injects after provisioning. The chart reads
  `secretName` and projects that Secret with `envFrom`; the password is
  deliberately not among them, because Helm values are logged in full and
  persisted into the deployment's own namespace.

## Runtime configuration

Whatever vars the deployment has set arrive in the container as environment
variables. The platform writes them into a Secret named
`<release>-vars-<number>` in the deployment's own namespace before Helm runs,
and passes the chart only the Secret's *name* under `caelus.vars.secretName` —
values never travel through the Helm values, which are logged in full and
persisted into a tenant-namespace object.

One Secret per rollout, so a failed deploy that rolls back leaves the previous
one intact; superseded Secrets are removed after the next successful deploy.

A deployment with no vars gets no Secret and no `envFrom` source at all, rather
than an empty one.

**The platform's variables win.** The vars Secret is the *first* `envFrom`
source, with the object-storage credentials after it, and `PORT` is set as an
explicit `env` entry — which outranks every `envFrom` source. So a var that
happens to be named `AWS_SECRET_ACCESS_KEY` cannot displace the real
credential. The API also refuses to store a var under the `CAELUS_`, `AWS_`,
`S3_` or `RAILPACK_` prefixes, or named `BUCKET_NAME` or `PORT`; the ordering
is the second line of defense, because the two fail differently.

## SSH access

`custom` declares an **application-container session root**: a platform SSH
sidecar rides in the application pod, and the deployment's owner reaches it with
stock `ssh`, using an SSH key registered on their account. What that grants, and
why, is
[ssh-chart-contract](../../openspec/specs/ssh-chart-contract/spec.md) and
[ssh-session-dispatcher](../../openspec/specs/ssh-session-dispatcher/spec.md) ·
Rationale:
[unified-ssh-sidecar](../../openspec/changes/archive/2026-09-03-unified-ssh-sidecar/design.md).

```bash
ssh <deployment>@dev.freepod.eu                   # a login shell IN the application container
ssh <deployment>@dev.freepod.eu psql              # the PostgreSQL toolbox, in the sidecar
scp ./config.yml <deployment>@dev.freepod.eu:/app/  # a file, into the application container
sftp <deployment>@dev.freepod.eu                  # or browse it
freepod cp ./assets :/app/assets                  # or the client's own copy
```

**The shell lands in the container the tenant built**, not in the sidecar. The
pod shares its process namespace, so the sidecar reaches the application's
filesystem and environment and enters it; what a session can do there is a
property of that image, and a distroless one with no shell ends the session
saying so.

**File transfer needs nothing in your image.** It is served by the sidecar's own
`sftp-server`, chrooted into the application container — so `scp`, `sftp`,
`freepod cp` and any client that speaks the protocol work against a stock
deployment, whose Railpack base image carries no `sftp-server`, `scp` or `rsync`
of its own. A session starts in the application's working directory, so a
relative path means there what it means in `freepod shell`. Do not allocate a
terminal for a piped command (no `-t`): a pty translates line endings and folds
stderr into stdout, which corrupts the stream.

**Debugging a broken deployment is the point.** A deployment in `error` state is
still reachable — the Service publishes not-ready addresses and the edge's
reachability allowlist admits `error` deliberately — because that is the state
an owner most needs to get inside.

**Attaching a debugger or profiler is not available yet.** `strace`, `gdb` and
`py-spy` need `CAP_SYS_PTRACE`, which Pod Security `baseline` refuses at
admission; raising that is a change to what the platform guarantees about tenant
pods and is tracked separately. Everything else — the shell, file transfer, the
toolbox and forwarding — works without it.

### Forwarding to the database

One destination is forwardable — the deployment's own database, through the
pooler — and it must be spelled exactly. **The address is per environment**,
because it names the pooler Service in that environment's namespace:

| Environment | Forward to |
|---|---|
| production (`freepod.eu:22`) | `caelus-tenant-pooler.caelus.svc.cluster.local:6432` |
| dev (`dev.freepod.eu:23`) | `caelus-tenant-pooler.caelus-dev.svc.cluster.local:6432` |

```bash
# production
ssh -N -L 5432:caelus-tenant-pooler.caelus.svc.cluster.local:6432 <deployment>@freepod.eu
# dev
ssh -p 23 -N -L 5432:caelus-tenant-pooler.caelus-dev.svc.cluster.local:6432 <deployment>@dev.freepod.eu
```

Then connect a local client to `localhost:5432`.

The spelling is not cosmetic. `PermitOpen` matches the destination **as the
client wrote it** and resolves the name afterwards, so
`caelus-tenant-pooler.caelus.svc:6432` and the fully qualified form above are
not interchangeable. A mismatch is refused with `administratively prohibited`,
which reads like a permissions problem rather than a typo. The addresses in this
table and the value the chart renders into `FREEPOD_PERMIT_OPEN` are one fact
with two readers, and `api/tests/test_custom_ssh_sidecar.py` fails if they drift
apart.

Every other destination is refused. Tenant egress reaches the public internet on
every port, so an unconstrained forwarder would be an authenticated open TCP
relay originating from the platform's own address.

The database client also works with the application container stopped — the
connection details are in the *sidecar's* environment, not read out of the
application process, which is unavailable in precisely the situation an owner is
investigating.

## The ownership assertion

`custom.imageRef` in
[`chart/templates/_helpers.tpl`](chart/templates/_helpers.tpl) asserts that the
`{user_id}` repository half of `image` equals `caelus.owner.id`, and `fail`s if
not:

```
Error: execution error at (custom/templates/deployment.yaml:24:20): custom: image
repository "7" does not match deployment owner "5"; an image can only be deployed
by the user it was built for
```

The message names both values on purpose — it surfaces to the end user as a
deployment error, and a raw Helm template error would tell them nothing.

Two properties make this sound, and **both must hold**:

1. `caelus.owner.id` is injected by
   `_build_owner_overrides` (`api/app/services/reconcile.py`), and
   `merge_values_scoped` (`api/app/services/template_values.py`) applies system
   overrides **last** — so a tenant cannot shadow it with their own values. There
   is a test pinning this ordering in `api/tests/test_reconcile_service.py`.
2. `placeholderImage` is a system value. It is the one image reference that
   bypasses this check, which is exactly why it must never become
   user-settable — that would hand every tenant an arbitrary-image escape hatch.

The check lives in the chart rather than in `update_deployment` so that no build-
or image-specific special-casing leaks into the generic deployment path shared by
every other product.

## No image yet: the placeholder

`freepod init` creates the deployment — and claims and routes its hostname —
*before* anything has been built. With `image` unset the chart renders and
installs cleanly, running `placeholderImage` rather than scaling to zero, so a
freshly claimed domain serves a real page instead of a Traefik 503.

The placeholder is built from [`placeholder/`](placeholder/): nginx serving one
self-contained landing page (no external CSS, fonts, or images — it has to render
standalone, on a hostname with nothing else behind it).

It is published to `ghcr.io/erikvanzijst/freepod/custom-placeholder`, tagged
from `placeholder/VERSION`, and CI publishes it on merge when that version is
new. To publish by hand, from the repository root:

```bash
./scripts/build-images.sh --placeholder
```

A published version is never overwritten: bump `placeholder/VERSION`, then
repoint `placeholderImage` in `chart/values.yaml` and
`products/catalog/custom.yaml` and bump the chart version with it, so running
deployments are not swapped out from under themselves by a mutated tag.

## Manual install

```bash
helm lint products/custom/chart
helm template demo products/custom/chart          # placeholder, no ingress

helm upgrade --install demo products/custom/chart \
  --namespace demo --create-namespace \
  --set image=5@sha256:<64 hex chars> \
  --set caelus.owner.id=5 \
  --set caelus.ingress.enabled=true \
  --set caelus.ingress.host=demo.example.com \
  --set caelus.ingress.tls.wildcard=true
```

Both `helm lint` and `helm template` pass standalone with the shipped defaults:
`image` is empty (placeholder) and `caelus.ingress.enabled` is `false`.

## Build and publish

Published to `oci://ghcr.io/erikvanzijst/freepod/charts/custom` by
[`scripts/publish-charts.sh`](../../scripts/publish-charts.sh), which CI runs on
every merge to `master`: bump `version` in `chart/Chart.yaml` and that version
is published. To publish by hand, from the repository root:

```bash
./scripts/publish-charts.sh custom
```

## Caelus product template

| Field               | Value                                                                                                                                              |
|---------------------|----------------------------------------------------------------------------------------------------------------------------------------------------|
| Chart ref           | `oci://ghcr.io/erikvanzijst/freepod/charts/custom`                                                                                                 |
| Chart version       | `0.9.2`                                                                                                                                            |
| Default Helm values | `{}` — the chart's own defaults already carry `registry`, `placeholderImage`, and `containerPort`. Set them here only to override per environment. |
| User values schema  | see below                                                                                                                                          |

### User values schema

The `values_schema_json` for the template row. This is a **different, much
smaller** schema than `chart/values.schema.json`: that one validates the fully
merged values Helm-side, this one defines the two fields a tenant may set and
drives the deployment form.

Two values are required:

- `hostname` carries `"title": "hostname"`. `_iter_hostname_paths` /
  `normalize_and_return_hostname` (`api/app/services/deployments.py`) scan the
  schema for that title (case-insensitively) to derive and claim the deployment's
  hostname. Without it, hostname claiming silently does nothing.
- `image` is **not** in `required`. The deployment is created before any build
  exists; requiring it would make `freepod init` impossible.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "hostname": {
      "type": "string",
      "title": "hostname",
      "description": "The domain name your application is served on",
      "minLength": 1,
      "maxLength": 253,
      "pattern": "^((?!-)(xn--)?[a-z0-9][a-z0-9-_]{0,61}[a-z0-9]?\\.)+(xn--)?[a-z0-9-]{2,}$"
    },
    "image": {
      "type": "string",
      "title": "Image",
      "description": "The build to run, as \"{user_id}@{digest}\". Leave empty to serve the placeholder page until your first build is released.",
      "pattern": "^[0-9]+@sha256:[a-f0-9]{64}$"
    }
  },
  "required": [
    "hostname"
  ],
  "additionalProperties": false
}
```
