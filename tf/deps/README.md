# Shared Dependencies

This Terraform project manages cluster-wide singleton services that are
shared across all Caelus environments (dev and prod). It has its own
independent state and does not use Terraform workspaces.

## What It Creates

- `keycloak` namespace, deployment, Postgres database, PVC, service, ingress.
  Keycloak runs a **custom image** (`var.keycloak_image`) with the Freepod
  login/account/email theme baked in — see [Keycloak theming](#keycloak-theming).
- The **`freepod` Keycloak realm** and its clients, client scopes and groups,
  declared as Terraform in `keycloak-config/` — see
  [Keycloak configuration](#keycloak-configuration).
- `echo` namespace, deployment, service, ingress
- `monitoring` namespace with the cluster-wide observability stack (Loki +
  Promtail, Prometheus + node-exporter + kube-state-metrics + Alertmanager,
  Grafana) — see [Monitoring stack](#monitoring-stack).
- `garage` namespace with **Garage**, the shared S3-compatible object store,
  published at `blob.freepod.eu` — see [Garage object store](#garage-object-store).
  Requires a [one-time cluster-layout bootstrap](#cluster-layout-bootstrap)
  before it will serve anything.
- `caelus-tls` namespace (`tls/`) holding the platform wildcard certificate and
  the `TLSStore/default` Traefik serves from. The store is platform-owned rather
  than rendered by the Traefik release, and Traefik is pinned to this namespace
  with `providers.kubernetesCRD.defaultTLSResourcesNamespace` — a `default` store
  anywhere else is then ignored instead of making Traefik honour none of them.
  Terraform owns the default certificate; the reconciler owns the membership
  list. Spec:
  [platform-tls-store](../../openspec/specs/platform-tls-store/spec.md),
  [freepod-tls-termination](../../openspec/specs/freepod-tls-termination/spec.md)
  · Rationale:
  [per-user-tls-certificates](../../openspec/changes/per-user-tls-certificates/design.md)

## Prerequisites

- Terraform `>= 1.0`
- Access to the Kubernetes cluster via `../../k8s/kubeconfigs/dev-k3s.yaml`

## Configuration

Create `secrets.auto.tfvars` (gitignored):

```hcl
keycloak_admin_password = "replace-with-actual-password"

# Monitoring stack
grafana_admin_password = "replace-with-actual-password" # break-glass local admin
alert_email_to         = "ops@example.com"              # Alertmanager recipient

# Garage object store
#   garage_admin_token: openssl rand -base64 32
#   garage_rpc_secret:  openssl rand -hex 32   (Garage requires exactly 32 bytes hex)
garage_admin_token = "replace-with-actual-token"
garage_rpc_secret  = "replace-with-64-hex-characters"
```

Grafana's OIDC client ID and secret are **not** configured here. The `grafana`
client is Terraform-managed (see [Keycloak configuration](#keycloak-configuration)),
so `module.prometheus` reads them straight from `module.keycloak_config`.

The monitoring stack needs no external SMTP credentials: Alertmanager relays
email through the in-cluster `mailer` service.

## Deploy

```bash
cd tf/deps
terraform init
terraform apply
```

## Monitoring stack

A **cluster-wide** observability stack in the `monitoring` namespace, shared by
all Caelus environments (it is *not* duplicated per env). Modules:

- `loki/` — Loki (SingleBinary, filesystem-backed, ~10Gi PVC) + a Promtail
  DaemonSet that ships every pod's logs to Loki, including parsed Traefik
  access logs. **Retention is enforced** — see below.

  > **The `namespace`, `instance` and `release_id` stream labels are a contract,
  > not operator convenience.** The Caelus API builds every LogQL selector for
  > `freepod log` out of exactly those three: `namespace` is the per-user
  > namespace, `instance` is `deployment.name` (the Helm release name), and
  > `release_id` comes from the `caelus.dev/release-id` pod label that the
  > `custom` chart renders. Renaming or dropping any of them breaks a
  > user-facing feature, not a dashboard. A pod without the release label
  > collects exactly as before, with no `release_id` and no error, which is how
  > every platform pod and every curated product behaves.
  >
  > Retention is `limits_config.retention_period` plus
  > `compactor.retention_enabled`. Note that `compactor.replicas` at the top
  > level is **inert** in SingleBinary mode — the chart only renders that
  > StatefulSet when `deploymentMode` is `Distributed`, and the compactor
  > already runs in-process under `-target=all`. Raising it would start a
  > second compactor competing over the same filesystem store. Enabling
  > retention without `compactor.delete_request_store` is a hard startup
  > `CONFIG ERROR`.
  >
  > Promtail's rendered config lives in a **Secret**, not a ConfigMap:
  > `kubectl -n monitoring get secret promtail -o jsonpath='{.data.promtail\.yaml}' | base64 -d`.
- `prometheus/` — the `prometheus-community/prometheus` chart (bundles
  node-exporter for node CPU/mem/net/disk, kube-state-metrics for workload
  state, and Alertmanager), plus **Grafana** (mirrors the homelab layout). A
  forked `prometheus/scrape_configs.yaml` drops high-cardinality control-plane
  histogram buckets for the single node — **reconcile it when bumping the chart
  version**.

Runtime dependencies on other `tf/deps` singletons:

- **`keycloak`** — Grafana authenticates via OIDC and whitelists users by
  Keycloak group (see bootstrap below).
- **`mailer`** — Alertmanager delivers alert email through
  `smtp.mailer.svc.cluster.local:25` (no external SMTP secrets here).

### Access

Only **Grafana** is exposed, at `https://grafana.freepod.eu` (bare Traefik
ingress, no forward-auth — Grafana runs its own Keycloak login).

Prometheus and Alertmanager are **ClusterIP only** — reach them with
`kubectl port-forward`:

```bash
kubectl -n monitoring port-forward svc/prometheus-server 9090:80        # Prometheus UI → http://localhost:9090
kubectl -n monitoring port-forward svc/prometheus-alertmanager 9093:9093 # Alertmanager  → http://localhost:9093
```

### Grafana OIDC (Terraform-managed)

Nothing to bootstrap by hand. The `grafana` client, the
`freepod-observability` group and the `groups` client scope with its
group-membership mapper are all declared in `keycloak-config/` — see
[Keycloak configuration](#keycloak-configuration). `module.prometheus` reads
the client ID and generated secret directly from `module.keycloak_config`, so
no Grafana OIDC secret is maintained by hand.

Granting Grafana access is pure group membership: add the user to
`freepod-observability` in the Keycloak admin console. No Terraform apply.

Two settings that look optional but are not, both in
`prometheus/grafana.tf`:

- `groups_attribute_path = "groups"` — Grafana's `extractGroups()` returns an
  empty list without it, so the `groups` claim is never read and every login
  is rejected as "not a member of one of the required groups".
- **No `use_pkce`**, matched by no `pkce_code_challenge_method` on the
  `grafana` client. Grafana only sends a code challenge when `use_pkce` is
  true; setting the client attribute alone makes PKCE mandatory at Keycloak
  and fails every Grafana login. Enable both together or neither. (The
  oauth2-proxy clients *do* require PKCE and set the matching flag.)

## Garage object store

[Garage](https://garagehq.deuxfleurs.fr/) is the platform's S3-compatible
object store: one instance in the `garage` namespace, shared by **both**
environments (`tf/deps` is workspace-less). It exists so the Caelus API can mint
**presigned URLs** — the API holds the only S3 credentials, the bytes never
transit the API pod, and each grant is scoped to one object and expires by
itself.

Deployed as hand-written resources in `garage/`, not a Helm chart: Garage's
chart is not published to any Helm repo or OCI registry, so using it would mean
vendoring somebody else's templates and reconciling them on every bump (the same
tax the forked Prometheus `scrape_configs.yaml` already carries). Garage is a
single static binary with a TOML config; the module is a ConfigMap, a
StatefulSet with two `volumeClaimTemplates`, two Services, an Ingress and a
provisioning Job.

### Endpoint

`https://blob.freepod.eu` — S3 API only. TLS comes from Traefik's default
certificate store (`wildcard-freepod-eu-tls`), so there is **no cert-manager
`Certificate` and no ACME challenge here**: `blob` is one label deep and
therefore inside `*.freepod.eu`. A two-label host like `blob.objects.freepod.eu`
would fall outside the wildcard and force per-app issuance for no gain.

**The ingress deliberately carries no `forward-auth` middleware.** That is the
load-bearing decision of this deployment, and the reasoning lives in a comment
on the resource itself (`garage/ingress.tf`) — read it before changing anything
there. In short: Garage authenticates with S3 SigV4, and oauth2-proxy both
rejects those requests (no session cookie) and rewrites them so the signature no
longer verifies. Authentication is not weakened, only relocated — into Garage's
SigV4 check and into the API's control over who gets a presigned URL.

The **admin API (:3903) is never routed from outside the cluster.** It can mint
access keys and rewrite the cluster layout. Reach it with:

```bash
kubectl -n garage port-forward svc/garage 3903:3903
kubectl -n garage exec garage-0 -- /garage status
```

Note that `kubectl exec` can only run `/garage` directly — the image is a
`FROM scratch` image whose single file is that binary. There is no shell in it.

### Cluster-layout bootstrap

**A fresh Garage node holds no cluster layout and rejects every request until
one is assigned and committed.** This is the first thing to check when a new
install returns errors — `/health` reports 503 and the provisioning Job fails
with a message pointing back here.

Terraform does not do this: the layout is keyed on a node ID that does not exist
until the pod has run, and a wrong layout is not cheaply reversible.

The node ID is generated on first boot and stored in the metadata PVC, so it
cannot be known ahead of time — read it from the running pod. It is shown as a
16-character prefix of the full key, which is what `layout assign` expects:

```
==== HEALTHY NODES ====
ID                Hostname  Address         Tags  Zone  Capacity          …
9a6b59a6829a6e43  garage-0  127.0.0.1:3901              NO ROLE ASSIGNED  …
```

```bash
# 1. Read the node ID. The `NO ROLE ASSIGNED` match is a guard: once a role is
#    assigned that text is gone, so this comes back empty on an already
#    bootstrapped node rather than letting you re-assign it.
NODE_ID=$(kubectl -n garage exec garage-0 -- /garage status 2>/dev/null \
  | awk '/NO ROLE ASSIGNED/{print $1}')
echo "node id: ${NODE_ID:?no unassigned node found - already bootstrapped?}"

# 2. Assign capacity matching the data PVC (var.data_pvc_size, default 20Gi).
#    20G reads as ~18.6 GiB, deliberately under the PVC rather than over.
kubectl -n garage exec garage-0 -- /garage layout assign -z dc1 -c 20G "$NODE_ID"
kubectl -n garage exec garage-0 -- /garage layout apply --version 1

# 3. Verify: the node has a zone and capacity, and nothing is pending
kubectl -n garage exec garage-0 -- /garage status
kubectl -n garage exec garage-0 -- /garage layout show
```

The pod does not need to be `Ready` for this — it will not be, until the layout
is committed. It only needs to be `Running`.

`layout show` must report a current layout version and no staged changes. Once
committed, the pod passes its readiness probe and `terraform apply` proceeds.

**Repeat this whenever the node identity changes** — most plausibly if the
metadata PVC is deleted and recreated, which mints a new node key. The buckets
and keys are re-created by the Job, but the layout is not.

> The first `terraform apply` on a clean cluster will sit waiting in the
> provisioning Job for up to 10 minutes. That wait is deliberate: do the
> bootstrap above in a second terminal and the same apply completes. Otherwise
> the Job fails with instructions and you re-run the apply afterwards.

### Buckets, keys and expiry

Provisioned by a single-container Kubernetes Job (`garage/provisioning.tf`,
running `garage/scripts/provision.sh`) that Terraform re-runs whenever its
script or inputs change. Garage has no IAM, so there is no S3-policy-shaped
Terraform resource to use, and `ImportKey` rejects keys Garage did not
generate — so Garage must mint the key material and the Job reads it back into
a `garage-keys` Secret.

| | dev | prod |
|---|---|---|
| bucket | `dev` | `prod` |
| access key | `caelus-api-dev` | `caelus-api-prod` |
| grant | read+write on `dev` | read+write on `prod` |

Names are derived from `var.environments`, not hardcoded per resource. Each key
has permission on **its own bucket only**, so a leaked dev credential cannot
reach prod objects — enforced by Garage, not by convention.

Every step reads before it writes, so **re-running the Job is a no-op**: an
existing access key is never rotated, and the lifecycle rules are assigned
wholesale rather than appended, so they converge instead of accumulating.
Re-running also repairs drift, which is the answer to "someone changed
something with `kubectl exec`".

Each bucket carries both lifecycle rules Garage implements, at
`var.object_expiry_days` (default 2):

- `Expiration` — reclaims completed objects.
- `AbortIncompleteMultipartUpload` — reclaims parts of uploads that never
  completed. **Not optional**: those parts consume disk while never appearing in
  a bucket listing, which is exactly how storage leaks invisibly on a node with
  a history of disk pressure.

Declarative expiry is why there is no reaper CronJob and no cleanup code.

The Job talks to the **admin API** for all of it — buckets, keys, grants and
lifecycle — and to nothing else. Not the `garage` CLI: that speaks RPC and
needs `<full-node-id>@host:port`, which cannot be known by a second pod, and it
cannot be scripted inside the shell-less Garage image anyway. And no S3 client
either: setting lifecycle used to require one (`PutBucketLifecycleConfiguration`
is an S3-API call), which is why this Job once had a second container in an
`amazon/aws-cli` image, but Garage v2.3.0's `POST /v2/UpdateBucket` accepts
`lifecycleRules` directly in the same S3-shaped JSON. The Job mints a **scoped,
expiring admin token** for the actual work and revokes it on exit.

### Reading the S3 credentials

Garage generates the key material, so it only exists after an apply:

```bash
terraform output -raw garage_access_key_id_dev       # -> tf/app "default" key
terraform output -raw garage_secret_access_key_dev
terraform output -raw garage_access_key_id_prod      # -> tf/app "prod" key
terraform output -raw garage_secret_access_key_prod
```

Paste into `tf/app/secrets.auto.tfvars` as **workspace-keyed maps** — a scalar
cannot carry two per-environment values, because `*.auto.tfvars` is auto-loaded
in every workspace. **The dev workspace is named `default`, not `dev`:**

```hcl
s3_access_key_ids = {
  default = "GK…"   # dev
  prod    = "GK…"
}
s3_secret_access_keys = {
  default = "…"
  prod    = "…"
}
```

`tf/app` builds the `caelus-s3` Secret from these and mounts it on the API with
`env_from`, the `caelus-db` pattern. The two root modules are deliberately not
coupled with `terraform_remote_state` — same handoff ritual as the Keycloak
client secrets.

### Reading the Caelus API's admin token

The API provisions a bucket and an access key per storage-enabled deployment at
reconcile time, so it holds a Garage admin token of its own:

```bash
terraform output -raw garage_caelus_api_admin_token
```

A **scalar**, not a workspace-keyed map: every environment provisions on the one
shared instance and the scope is identical, so both `tf/app` workspaces take the
same value.

```hcl
garage_admin_token = "…"
```

Two things about it that the S3 credentials above do not share:

- **It is far more powerful.** Those four values reach one bucket each. This one
  administers buckets and keys across the instance and can read back the secret
  of any access key it can see — so a compromise of the API is a compromise of
  every tenant bucket. It is scoped (no cluster status, no layout changes, and
  Garage refuses `CreateAdminToken`/`UpdateAdminToken` inside a scope as trivial
  privilege escalation), which bounds what else it can do but not that.
- **Its secret cannot be read back from Garage.** `CreateAdminToken` returns it
  exactly once; `GetAdminTokenInfo` has no field for it. The `garage-keys` Secret
  is therefore its only store of record, and `provision.sh` reads it from there
  on every run. **If that Secret is lost, the token rotates** — the script
  cannot recover the old secret, so it deletes the orphaned token and mints a
  replacement, and you must re-paste it into `tf/app/secrets.auto.tfvars`. This
  is the one place where re-running the Job is not a pure no-op.

### Per-deployment tenant buckets

Terraform provisions the two artifact buckets above and nothing else. The Caelus
API provisions one bucket and one access key **per storage-enabled deployment**
at reconcile time, using the admin token above, so those never appear in this
module's state:

|                  | name                  | created by                   |
|------------------|-----------------------|------------------------------|
| artifact buckets | `dev`, `prod`         | this module, at apply        |
| tenant buckets   | `dep-<deployment-id>` | the Caelus API, at reconcile |

**Drained, alias-carrying buckets are expected residue, not a fault.** Deleting a
deployment deletes its access key and sets a one-day object-expiry rule; the
bucket itself is left behind, because Garage refuses to delete a non-empty
bucket and enumerating a tenant's objects synchronously is not viable inside a
reconcile. What remains is an empty bucket no credential can reach, still
carrying its `dep-<deployment-id>` alias.

Nothing sweeps them up yet. When something does, note that the signal is "this
alias names a deployment that is deleted in the database" — so **the reaper needs
a database session**, not merely an admin token, and cannot be a standalone
CronJob.

### Known limits

Recorded plainly, because they decide whether a future use case fits:

- **No object versioning.** Garage does not implement it. An overwrite is
  unrecoverable and there is no point-in-time recovery.
- **No IAM, no bucket policies, no ACLs.** Access control is Garage's own
  per-access-key-per-bucket model, and nothing finer exists.
- **Single node, single replica, no backup.** Losing the PVC loses the objects.

These are acceptable for write-once / read-once ephemeral blobs and for nothing
else. Anything durable — backups, user content, anything needing recovery or
multi-tenant policy — needs a fresh evaluation, not an extension of this one.

### Things that will bite you

- **Attaching `forward-auth` to the S3 ingress breaks every upload and
  download.** It is not a missing safeguard, it is a requirement. See the
  comment in `garage/ingress.tf` before you touch it.
- **Setting `root_domain` in `garage.toml` breaks TLS.** It enables vhost-style
  addressing, putting the bucket in the hostname
  (`dev.blob.freepod.eu`) — two labels deep, so outside the `*.freepod.eu`
  wildcard, with no DNS record either. Path-style is always enabled, so leaving
  `root_domain` unset costs nothing. The matching requirement on the client side
  is `addressing_style: "path"` (see `api/app/config.py`).
- **No layout means no service, and the symptom does not say so.** A fresh
  install, or a recreated metadata PVC, returns errors on everything until the
  [bootstrap](#cluster-layout-bootstrap) is run.
- **Adding a `buffering` middleware or a body-size cap anywhere in the Traefik
  path breaks large uploads.** Nothing configures one today; keep it that way:

  ```bash
  grep -rn 'buffering\|maxRequestBodyBytes' tf/ --include='*.tf' \
    --include='*.tftpl' | grep -vE ':[[:space:]]*#'   # must print nothing
  ```
- **`terraform destroy` deletes the PVCs and the objects with them.** There is
  no backup, by design.

## Keycloak configuration

The `freepod` realm — the realm Freepod end users authenticate against — is
declared as Terraform in `keycloak-config/`, using the `keycloak/keycloak`
provider. This is separate from the `keycloak/` module, which deploys the
Keycloak *server*; `keycloak-config/` configures what runs inside it.

What it manages:

- The `freepod` realm: registration open, email verification required,
  self-service password reset, the `freepod` login/email/account themes, and
  SMTP pointed at the in-cluster mailer relay.
- Clients `freepod-prod`, `freepod-dev` (per-environment, PKCE `S256`, direct
  access grants off) and `grafana`.
- Public clients `freepod-cli-prod` and `freepod-cli-dev` for external API
  clients: no secret, PKCE `S256` required, device authorization grant on,
  loopback redirect URIs.
- The `groups` client scope and its group-membership mapper.
- The `freepod-api-prod` / `freepod-api-dev` audience scopes, which put the
  environment's oauth2-proxy client ID into the access token's `aud` claim.
- Groups `freepod-dev` and `freepod-observability`.

**Apply `tf/deps` before `tf/app`.** oauth2-proxy fails its readiness probe if
OIDC discovery does not resolve, so the realm, clients and scopes must exist
before the edge is configured to use them.

**Admin-console edits to any managed attribute are reverted on the next
`terraform apply`.** Change these in code.

Deliberately *not* managed, and safe to change by hand:

- **End-user accounts.** There is no `keycloak_user` resource. Users live in
  Keycloak's own Postgres, and self-registration causes no drift.
- **Group membership.** Terraform owns the groups, not who is in them.

### Things that will bite you

- **`groups` is not a Keycloak built-in client scope.** Keycloak 24.0.5 ships
  ten default scopes and `groups` is not among them, so the scope and its
  mapper are declared here rather than merely attached. The mapper sets
  `full_path = false`, so the claim carries bare names (`freepod-dev`), which
  is what `allowed_groups` compares against.
- **The provider is pinned `~> 5.7.0`.** From 5.8.0 it unconditionally sends
  `bruteForceStrategy`, a field added in Keycloak 26; Keycloak 24.0.5 rejects
  the whole request with `400 unable to read contents from stream` and realm
  creation fails. Raise the cap only together with a Keycloak upgrade.
- **The realm carries two destroy guards.** `prevent_destroy` guards the plan
  but only while the resource block exists in the configuration;
  `terraform_deletion_protection` is enforced by the provider at the delete
  call and survives the block being removed. Deleting the realm on purpose
  means clearing both.
- **The `freepod-api-*` audience scopes are load-bearing for authentication.**
  A Keycloak access token otherwise carries `aud: ["account"]` and names the
  requesting client only in `azp`, which oauth2-proxy's audience check rejects.
  They are also what stops a dev token working on prod: both CLI clients
  register identical loopback redirect URIs, so `aud` is the only thing
  separating the environments. Never assign one environment's audience scope to
  the other's client, and never add them to `local.default_client_scopes` —
  that local is applied to every client, which would hand each one both
  audiences.
- **A `kubectl rollout restart` on the Keycloak deployment shows up as drift.**
  Terraform removes the `kubectl.kubernetes.io/restartedAt` annotation on the
  next apply, which restarts the pod. That is a brief authentication outage for
  prod, dev and Grafana at once — and if the same apply also creates Keycloak
  provider resources, they race the restart and fail with `502 Bad Gateway`.
  Reconcile that drift on its own, or re-run the apply once the pod is Ready.

### Reading client secrets

Secrets are generated by Keycloak and surfaced as outputs:

```bash
terraform output -raw freepod_dev_client_secret   # -> tf/app "default" key
terraform output -raw freepod_prod_client_secret  # -> tf/app "prod" key
```

The two root modules are deliberately not coupled with
`terraform_remote_state`; paste these into `tf/app/secrets.auto.tfvars`.


## Keycloak theming

Keycloak's login, account console and transactional emails are themed to match
the freepod.eu landing page (dark "digital sovereignty" look, Fraunces/Schibsted
Grotesk type, gradient CTAs).

### Where the theme lives

```
keycloak/theme/freepod/
  login/     # FreeMarker + CSS: sign-in, register, reset, OTP, errors
  account/   # PatternFly-v4 SPA skin: profile / "Personal info" pages
  email/     # FreeMarker: password reset, verify email, admin actions
```

Each type has its own `resources/` (the fonts are self-hosted per type, copied
from the UI's `@fontsource` packages — no Google Fonts calls). One stylesheet
per type rebrands every screen of that type, because all screens share the
type's `template.ftl`.

### How it's deployed (production)

The theme is **baked into the Keycloak image** rather than mounted (it's ~22
files / ~400KB — too much for a ConfigMap). `keycloak/Dockerfile` is just
`FROM quay.io/keycloak/keycloak:24.0` + `COPY theme/freepod`. Build, push and
roll out:

```bash
./scripts/build-images.sh --keycloak     # build + push ghcr.io/<owner>/caelus/keycloak
cd tf/deps && terraform apply            # if var.keycloak_image / digest changed
kubectl rollout restart deployment/keycloak -n keycloak
```

The deployment references `var.keycloak_image`
(default `ghcr.io/erikvanzijst/freepod/keycloak:latest`).

### Assigning the theme to the realm

Baking the theme into the image only makes it *available*; the realm must
select it. For the `freepod` realm this is **Terraform-managed** — see
`keycloak-config/realm.tf`:

```hcl
login_theme   = "freepod"
email_theme   = "freepod"
account_theme = "freepod"
```

Setting it by hand in the admin console (Realm settings → Themes) works, but
is reverted on the next `terraform apply`. For an unmanaged realm such as
`master`, set it manually:

```bash
kcadm.sh update realms/master -s loginTheme=freepod -s accountTheme=freepod -s emailTheme=freepod
```

### Local theme development

There is no Keycloak in the local dev stack, so iterate against a **throwaway
Keycloak container**. Two quirks of running Docker from inside the dev container
(sibling containers via the mounted Docker socket) shape the commands below:

- **Bind-mount sources are *host* paths**, not dev-container paths — so we mount
  the host directory backing `/workspace/src`.
- **Port publishing happens on the host**, where the dev container already owns
  the forwarded ports (`8501`, `8000`). So instead of `-p`, the throwaway
  containers **share the dev container's network namespace**
  (`--network container:<devcontainer>`) and listen on those ports directly.

```bash
DEVCTR=caelus-app-1   # this dev container, as the Docker host sees it
HOST_WS=$(docker inspect "$DEVCTR" --format \
  '{{range .Mounts}}{{if eq .Destination "/workspace/src"}}{{.Source}}{{end}}{{end}}')

docker run -d --name freepod-kc \
  --network "container:$DEVCTR" \
  -e KEYCLOAK_ADMIN=admin -e KEYCLOAK_ADMIN_PASSWORD=admin \
  -v "$HOST_WS/tf/deps/keycloak/theme/freepod:/opt/keycloak/themes/freepod:ro" \
  quay.io/keycloak/keycloak:24.0 \
  start-dev --http-port=8501 \
    --spi-theme-cache-themes=false --spi-theme-cache-templates=false \
    --spi-theme-static-max-age=-1
```

Then point the `master` realm at the theme and add a permissive client so the
login/account pages can be opened directly (`start-dev` uses an **in-memory DB**,
so this must be re-applied after every restart):

```bash
K="docker exec freepod-kc /opt/keycloak/bin/kcadm.sh"
$K config credentials --server http://localhost:8501 --realm master --user admin --password admin
$K update realms/master -s loginTheme=freepod -s accountTheme=freepod -s emailTheme=freepod \
    -s registrationAllowed=true -s resetPasswordAllowed=true
$K create clients -r master -s clientId=theme-preview -s enabled=true -s publicClient=true \
    -s standardFlowEnabled=true -s 'redirectUris=["*"]' -s 'webOrigins=["*"]'
```

Preview from the host (forwarded on `8501`):

- **Login** (and register / forgot-password): `http://localhost:8501/realms/master/protocol/openid-connect/auth?client_id=theme-preview&response_type=code&scope=openid&redirect_uri=http://localhost:8501/`
- **Account**: `http://localhost:8501/realms/master/account/` (sign in as `admin`/`admin`)

> **Caching gotcha.** Keycloak caches theme *resources* in memory even with
> `--spi-theme-cache-themes=false`. Login-CSS edits show on a normal reload, but
> account/email resource changes may keep serving stale bytes — recreate the
> container (`docker rm -f freepod-kc` + the `run` above) to flush, and add a
> `?cb=1` query to the URL so the browser refetches the new resource-version URL.

#### Previewing emails (Mailpit)

Emails are only produced by sending over SMTP — there's no in-browser preview.
Run [Mailpit](https://mailpit.axllent.org/) as a local SMTP sink (web inbox on
the forwarded `8000`):

```bash
docker run -d --name freepod-mailpit --network "container:$DEVCTR" \
  -e MP_SMTP_BIND_ADDR=0.0.0.0:1025 -e MP_UI_BIND_ADDR=0.0.0.0:8000 \
  axllent/mailpit
```

Point the realm's SMTP at it and give the test user an email address (kcadm
can't set the SMTP map, so use the REST API for that part):

```bash
TOKEN=$(curl -s -d client_id=admin-cli -d username=admin -d password=admin \
  -d grant_type=password \
  http://localhost:8501/realms/master/protocol/openid-connect/token | \
  python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -s -X PUT http://localhost:8501/admin/realms/master \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"smtpServer":{"host":"localhost","port":"1025","from":"no-reply@freepod.eu","fromDisplayName":"Freepod","ssl":"false","starttls":"false","auth":"false"}}'

AID=$($K get users -r master -q username=admin --fields id --format csv --noquotes | head -1)
$K update users/$AID -r master -s email=admin@freepod.eu -s emailVerified=true
```

Trigger sends, then read the rendered HTML at `http://localhost:8000`:

```bash
# password reset: use "Forgot Password?" on the login page, OR trigger admin emails:
curl -s -X PUT "http://localhost:8501/admin/realms/master/users/$AID/send-verify-email" \
  -H "Authorization: Bearer $TOKEN"
curl -s -X PUT "http://localhost:8501/admin/realms/master/users/$AID/execute-actions-email" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '["UPDATE_PASSWORD"]'
```

#### Cleanup

```bash
docker rm -f freepod-kc freepod-mailpit
```

## Notes

- Keycloak always uses the production domain (`keycloak.freepod.eu`).
- Echo uses `echo.freepod.eu`.
- This project must be deployed before `tf/app/`, since the app's
  OAuth2-proxy depends on a running Keycloak instance.
- Do NOT run `terraform destroy` here without understanding that it will
  take down Keycloak for all environments — and that it deletes Garage's PVCs,
  and every object stored in them. There is no backup by design; this store
  holds ephemeral transfer blobs only.
- A cluster-wide HSTS middleware (`headers-hsts`, `traefik.io/v1alpha1`) is
  defined in `system/hsts.tf` and attached as a default middleware on the
  `websecure` entrypoint only — see `system/helm/traefik/values.yaml.tftpl`.
  The `web` (:80) entrypoint is deliberately left untouched so ACME HTTP-01
  and the HTTP->HTTPS redirect are unaffected.
