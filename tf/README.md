# Terraform Infrastructure

This directory contains the Terraform infrastructure for Caelus, split into
two independent root modules:

- **`app/`** -- The Caelus application (API, UI, worker, OAuth2-proxy).
  Uses Terraform workspaces for dev/prod separation.
- **`deps/`** -- Shared singleton dependencies (Keycloak, Echo, the monitoring
  stack, and **Garage**, the S3-compatible object store at `blob.freepod.eu`).
  No workspaces; single instance shared across all environments.

Both projects deploy to the same Kubernetes cluster using the kubeconfig at
`../k8s/kubeconfigs/dev-k3s.yaml`.

## Why Two Projects?

Keycloak and Echo are cluster-wide singletons that must not be duplicated
when switching between dev and prod workspaces. Separating them into their
own Terraform root module (`deps/`) ensures they have independent state and
lifecycle from the workspace-multiplexed app resources.

## Deploy Order

Shared dependencies must exist before the app:

```bash
# 1. Deploy shared dependencies (one-time, no workspaces)
cd tf/deps
terraform init
terraform apply

# 2. Deploy the app (dev)
cd tf/app
terraform init
terraform workspace select default
terraform apply

# 3. Deploy the app (prod)
terraform workspace select prod || terraform workspace new prod
terraform apply
```

`tf/app` is workspace-scoped and the selection is **sticky**: it survives
between sessions, so a `terraform apply` run without checking which workspace
is selected will happily apply to the other environment. Run
`terraform workspace show` before planning, every time.

## TLS

Three things put a certificate in front of a request, and which one serves a
given connection is decided by server name during the handshake, before
routing:

- **The store's default certificate** — the `*.freepod.eu` wildcard, serving
  the apex and every single-label application hostname.
- **The store's membership list** — one certificate per account, covering
  everything under that account's own subdomain. Nothing is copied into a
  tenant namespace and no route references these: a certificate in the store is
  served to routes that know nothing about it, which is the whole point of it
  being a store rather than a per-route secret.
- **A route's own TLS secret** — custom domains, issued over HTTP-01 in the
  tenant's own namespace.

The store, the platform wildcard and every account certificate live in
`caelus-tls` (`tf/deps/tls`), because a store's certificate references carry no
namespace and resolve in its own. **All three are cluster singletons shared by
dev and prod** — `tf/deps` has no workspaces and the ingress controller honors
one store — so a change to any of them is never dev-only, whatever else is
being rolled out per environment.

Terraform owns the store's default certificate; the reconciler owns its
membership list, written with a version precondition as a separate field
manager. Neither may force its way past the other, and the flag that would is
named and forbidden in `tf/deps/tls/main.tf`.

Traefik is pinned to that namespace with
`providers.kubernetesCRD.defaultTLSResourcesNamespace`. Without the pin a
second store named `default` anywhere in the cluster makes Traefik honor
**neither**, serving its self-signed certificate for every hostname — measured,
not theorized. Requires Traefik >= 3.7.

Spec: [freepod-tls-termination](../openspec/specs/freepod-tls-termination/spec.md),
[platform-tls-store](../openspec/specs/platform-tls-store/spec.md) ·
Rationale:
[per-user-tls-certificates](../openspec/changes/per-user-tls-certificates/design.md)

## Build subsystem

`tf/app` also creates a per-environment builds namespace
(`caelus-builds` / `caelus-builds-dev`) where per-build Kubernetes Jobs run,
along with a permissionless ServiceAccount, a default-deny NetworkPolicy, and
the `caelus-build-worker` Deployment. It is the only namespace that runs
untrusted tenant code; see [`app/README.md`](./app/README.md) for why it is
per-environment and why it runs under Pod Security `privileged`.

Two node-level prerequisites are **not** captured by Terraform and are needed
again after any node rebuild (the userns sysctl for rootless BuildKit, and
containerd's trust for the internal registry). Both are documented in
[`../api/README.md`](../api/README.md) § Builds.

Spec: [build-worker](../openspec/specs/build-worker/spec.md),
[build-execution](../openspec/specs/build-execution/spec.md) · Rationale:
[add-build-subsystem](../openspec/changes/archive/2026-08-14-add-build-subsystem/design.md)

## Tenant database cluster

`tf/app` also creates the PostgreSQL 18 instance and PgBouncer pair that hold
every `custom` deployment's own database, per workspace.

The bootstrap SQL that creates the platform's roles runs as an init container
on the reconcile worker, so a change to it ships with the next rollout.

Spec: [tenant-database-cluster](../openspec/specs/tenant-database-cluster/spec.md) ·
Rationale:
[relational-storage](../openspec/changes/archive/2026-08-27-relational-storage/design.md)

## Secrets

Each project has its own `secrets.auto.tfvars` (gitignored):

- `tf/app/secrets.auto.tfvars`: `db_password`, `smtp_password`,
  `oauth2_proxy_client_ids`, `oauth2_proxy_client_secrets`,
  `oauth2_proxy_cookie_secret`, `s3_access_key_ids`, `s3_secret_access_keys`,
  `cloudflare_api_dns_token`, `cloudflare_zone_id` — the last two here rather
  than in `tf/deps` beside the other `cloudflare_*` values, because the root
  module that renders the reconciler's pod is the one that can reach them and
  the two roots share no state
- `tf/deps/secrets.auto.tfvars`: `keycloak_admin_password`, `smtp_*`,
  `cloudflare_*`, `grafana_admin_password`, `garage_admin_token`,
  `garage_rpc_secret`

`oauth2_proxy_client_ids`, `oauth2_proxy_client_secrets`, `s3_access_key_ids`
and `s3_secret_access_keys` are **maps keyed by workspace name**, not scalars —
Terraform auto-loads `*.auto.tfvars` for every workspace, so a scalar cannot
express two per-environment values:

```hcl
oauth2_proxy_client_ids = {
  default = "freepod-dev"   # NOTE: the dev workspace is named `default`
  prod    = "freepod-prod"
}
```

Read the secrets with `terraform output -raw freepod_dev_client_secret` (and
`…_prod_…`) in `tf/deps`. Grafana's OIDC client ID and secret need no tfvar at
all: `tf/deps` wires them straight from the Terraform-managed client.

The Garage S3 credentials cross the same boundary the same way — Garage
generates the key material, so it exists only after an apply:

```bash
cd tf/deps
terraform output -raw garage_access_key_id_dev       # -> s3_access_key_ids.default
terraform output -raw garage_secret_access_key_dev   # -> s3_secret_access_keys.default
terraform output -raw garage_access_key_id_prod      # -> …prod
terraform output -raw garage_secret_access_key_prod
```

One Garage instance serves both environments, separated by bucket and access
key (`dev` / `prod`), so mixing these up does not fail loudly — it points one
environment at the other's objects. See `tf/deps/README.md` § Garage object
store.

### Deployment var encryption keyring

`var_encryption_keys` carries the Fernet keys that encrypt every deployment
var. It is a **map of lists** keyed by workspace — one keyring per
environment, so a dev key cannot decrypt a prod tenant's secrets:

```hcl
var_encryption_keys = {
  default = ["<newest>", "<previous>"]   # NOTE: the dev workspace is `default`
  prod    = ["<newest>"]
}
```

Generate a key with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**Newest first. Only the first key encrypts; every key in the list decrypts.**
Each stored row records the *fingerprint* of the key that encrypted it, not its
position, so adding a key renumbers nothing and leaves history readable.

#### Introducing a key is two-phase

The API and the `caelus worker` share this keyring: the API encrypts a var when
it is written, and the worker decrypts the release's snapshot into the tenant's
namespace on every rollout. They are separate Deployments and roll
independently, so a key must be readable everywhere before it is written
anywhere.

**Phase A — distribute.** Append the new key to the **end** of the list and
apply. Every process can now decrypt with it; none encrypts with it, so restart
order does not matter.

```hcl
var_encryption_keys = {
  prod = ["<current>", "<new>"]   # new key last: decrypt-only
}
```

**Phase B — promote.** Move it to the front and apply again. Encryption
switches over, and by now every process can read what any other writes.

```hcl
var_encryption_keys = {
  prod = ["<new>", "<current>"]   # new key first: now it encrypts
}
```

**Skipping phase A breaks the reconciler**, and it breaks it late. The API would
encrypt with a key the worker does not hold, so the write succeeds and the
*rollout* fails — after the release row already exists — with every deployment
that touches a var stuck in `error` until the keyring is fixed. The failure
names the missing fingerprint, but it surfaces in a tenant's rollout rather
than in front of whoever edited the list.

The very first key is phase B with an empty prior list. That is safe only
because no encrypted row exists yet; every subsequent key needs both phases.

#### Retiring a key

After phase B, existing rows still name the old key. Sweep them onto the
current one, in batches, with the API image's own CLI:

```bash
# `caelus` in prod, `caelus-dev` in dev.
kubectl -n caelus exec deploy/caelus-worker -- caelus keyring-rotate
```

The sweep covers every column encrypted under the keyring — deployment vars
and tenant database passwords — not vars alone, which is why it is no longer
called `vars-rotate`.

It is resumable and safe to interrupt: a half-swept store is fully readable
because every row names its own key. Drop the old key from the list only after
every process has been rolled onto the new key list *and* a re-run reports
nothing left to rotate: the count is a snapshot, and a process still running
with the old key at the front keeps writing rows under it. The API and the
workers refuse to start if any stored fingerprint is not configured, so a
premature removal fails loudly at the next rollout rather than silently losing
data.

## Keycloak configuration is Terraform-owned

The `freepod` realm and its clients, client scopes and groups are declared in
`tf/deps/keycloak-config/` using the `keycloak/keycloak` provider. **Edits
made in the Keycloak admin console to any managed attribute are reverted on
the next `terraform apply` in `tf/deps`.** Change realm settings, client
settings, scopes and group *definitions* in code.

Two things are deliberately **not** Terraform-managed and are safe to change
by hand:

- **End-user accounts.** No `keycloak_user` resource exists. Users live in
  Keycloak's own Postgres; self-registration and account deletion produce no
  configuration drift.
- **Group membership.** Terraform owns the groups, not who is in them, so
  granting someone `freepod-dev` or `freepod-observability` access needs no
  apply.

The provider is pinned `~> 5.7.0`. From 5.8.0 it sends `bruteForceStrategy`,
a Keycloak 26 field that Keycloak 24 rejects outright, so raising the cap
requires upgrading Keycloak first. See `tf/deps/providers.tf`.
