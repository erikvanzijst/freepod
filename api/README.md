# Caelus API: Agent Onboarding Guide

This document is for engineers and coding agents who need to become productive in
this API codebase quickly.

## What This Project Is

`api/` is the control plane for provisioning user-owned web app instances on
Kubernetes.

It exposes two interfaces over the same business logic:
- FastAPI REST endpoints (`app/api/*.py`)
- Typer CLI commands (`app/cli.py`)

Core design rule: API and CLI are functionally equivalent for product/user/template/
deployment lifecycle operations. Both call the same service layer.

## Design Goals

- Keep API and CLI behavior in lockstep.
- Keep HTTP/CLI layers thin; put domain logic in `app/services/`.
- Treat database as source of truth for desired deployment state.
- Reconcile desired state to platform state through a queue-driven workflow.
- Enforce ownership boundaries: templates are scoped under products.
- Enforce ownership boundaries: deployments are scoped under users.

## Codebase Map

- `app/main.py`: FastAPI app wiring, routers, exception handlers.
- `app/cli.py`: Typer CLI commands; mirrors REST operations.
- `app/models.py`: SQLModel ORM + API read/write models.
- `app/db.py`: engine/session helpers and DB init.
- `app/api/`: REST route handlers.
- `app/services/`: domain services (single source of behavior).
- `app/services/reconcile.py`: deployment reconciliation orchestration.
- `app/services/jobs.py`: reconcile job queue operations.
- `app/services/builds.py`: build lifecycle (create, read, list, log slice).
- `app/services/artifacts.py`: presigned upload slots and artifact lookup.
- `app/services/build_jobs.py`: build Job manifest + the kubectl seam.
- `app/build_worker.py`: the build worker's claim/advance/recover pass.
- `app/provisioner.py`: Kubernetes/Helm adapter facade.
- `app/proc.py`: subprocess runner wrapper + command error normalization.
- `alembic/`: database migration history.
- `tests/`: API, CLI, service, and adapter tests.

## Authentication

Most API endpoints require the `X-Auth-Request-Email` header and return `404`
when it is absent. In production, Traefik routes requests through oauth2-proxy,
which injects the header — and the identity's Keycloak subject, as
`X-Auth-Request-User` — after Keycloak authentication (the `freepod` realm, one
session client per environment, dev additionally group-gated); in local
development the frontend sets both. The backend trusts the headers
unconditionally: `get_current_user` (`app/deps.py`) resolves the caller by the
subject — a record carrying it is reached by it alone, a record carrying none is
adopted by a matching email and stamped with the subject, and otherwise a new
record is created carrying both — and persists the subject on the record it
resolves to, so an email change updates the record in place instead of creating
a second account. A request with no subject resolves by email alone and neither
binds nor unbinds a record: a development and test path only, since an
edge-authenticated route always carries the subject and a `skip_auth_routes`
route must not be trusted to carry one (see the footgun below). `GET /api/me` is
the session initialization endpoint. Non-browser clients present a Keycloak
access token as `Authorization: Bearer`; the edge verifies it and injects the
headers from its claims, so the API cannot tell a token request from a browser
one — and on `dev.freepod.eu` a `401` can mean "not in the `freepod-dev` group"
as much as "no credential".

Spec: [caller-identity-resolution](../openspec/specs/caller-identity-resolution/spec.md),
[auth-header-integration](../openspec/specs/auth-header-integration/spec.md),
[oauth2-proxy-deployment](../openspec/specs/oauth2-proxy-deployment/spec.md),
[keycloak-deployment](../openspec/specs/keycloak-deployment/spec.md),
[keycloak-user-realm](../openspec/specs/keycloak-user-realm/spec.md),
[oauth2-token-auth](../openspec/specs/oauth2-token-auth/spec.md),
[authorization-guards](../openspec/specs/authorization-guards/spec.md),
[user-endpoint-authorization](../openspec/specs/user-endpoint-authorization/spec.md),
[product-endpoint-authorization](../openspec/specs/product-endpoint-authorization/spec.md) ·
Rationale:
[add-keycloak-oauth2-proxy](../openspec/changes/archive/2026-03-10-add-keycloak-oauth2-proxy/design.md),
[add-oauth2-token-auth](../openspec/changes/archive/2026-08-10-add-oauth2-token-auth/design.md)

### Public endpoints and the production `skip-auth` footgun

Several read-only endpoints are intentionally anonymous (no
`get_current_user` dependency) so the public landing page can work
before/without per-request auth:

- Products & templates: `GET /api/products`, `GET /api/products/{id}`,
  `GET /api/products/{id}/templates`,
  `GET /api/products/{id}/templates/{tid}`,
  `GET /api/products/{id}/icon`
- Plans: `GET /api/products/{id}/plans`, `GET /api/plans/{id}`,
  `GET /api/plans/{id}/templates`
- CNAME target: `GET /api/cname-target`
- SSH edge: `GET /api/ssh`
- Docs & schema: `GET /api/docs`, `GET /api/redoc`,
  `GET /api/openapi.json`
- Static files: `GET /api/static/*` (including product icons)

`POST /api/webhooks/*` is public in the app and deliberately *absent* from
`skip_auth_routes`: it reaches FastAPI through its own ingress
(`tf/app/caelus/ingress.tf`), which never passes through the forward-auth
middleware. Mollie POSTs there with no session, so the route bypasses the edge
gate rather than being excused from it.

`GET /api/me` is a related special case: it *does* run
`get_current_user`, returning the user when the header is present and
`404` when anonymous — that `404` is the signal the SPA uses to show the
landing page instead of the dashboard.

The authoritative public list is the union of "no `get_current_user` in
the route" (this codebase) and oauth2-proxy's `skip_auth_routes`
(`tf/app/login/main.tf`). Those two **must** match — see the footgun
below.

In production there are **two authentication layers in series**:

1. **Edge** (Traefik forward-auth → oauth2-proxy): rejects anonymous
   requests *before they reach FastAPI* and injects a trusted
   `X-Auth-Request-Email`.
2. **App** (`Depends(get_current_user)`): authorizes using that header.

Because the edge gate runs first, marking an endpoint public in the
FastAPI code is **not sufficient** to make it anonymously reachable in
production — the edge would still block it. The genuinely-public routes
are therefore *also* listed in oauth2-proxy's `skip_auth_routes` (see
`tf/app/login/main.tf`).

**⚠️ Footgun:** `skip_auth_routes` bypasses oauth2-proxy entirely for
matching requests, which has two dangerous consequences:

- **No trusted identity, no sanitization.** oauth2-proxy does not inject
  `X-Auth-Request-Email` on skipped routes, *and* it does not strip a
  client-supplied one. Never read `X-Auth-Request-Email` for
  authorization on any endpoint matched by a skip rule — a caller could
  spoof it.
- **Bearer tokens are ignored, not rejected.** The same bypass applies to
  `Authorization: Bearer`: a skipped route neither verifies the token nor
  derives an identity from it, so the request is anonymous no matter how
  valid the token is. A skipped route therefore cannot be made to behave
  differently for an authenticated client, and group gating on
  `dev.freepod.eu` does not apply to it either.
- **Two lists that must stay in sync.** Whether an endpoint is public is
  decided in *two* places — the FastAPI dependency (app layer) and the
  `skip_auth_routes` regexes (edge layer, in Terraform) — and they can
  drift:
  - Adding `Depends(get_current_user)` to a route still in the skip list
    makes it permanently anonymous in prod (the API `404`s every call).
  - Adding a new sensitive route under an overly-broad skip regex (e.g.
    `^/api/static/.*`, or a loose `^/api/products`) makes it anonymously
    reachable *and* identity-spoofable.

Keep skip regexes **anchored and narrow** (e.g. `GET=^/api/products$`,
`GET=^/api/products/[0-9]+/plans$`) and treat any change to which
endpoints are public as one that must be mirrored in **both** the API
code and `tf/app/login/main.tf`.

### CLI authentication

The CLI authenticates via the `CAELUS_USER_EMAIL` environment variable.
An optional `--as-user` flag overrides the env var:

```bash
# Via environment variable
export CAELUS_USER_EMAIL=alice@example.com
caelus list-users

# Via flag (overrides env var)
caelus --as-user bob@example.com list-users
```

Commands that require user context exit with code 1 and a clear error
when neither is configured.

Note this is an **operator** mechanism, not authentication: the CLI talks to
the database directly and simply asserts who it is acting as. It must run
next to the database and grants whatever the asserted email can do. External,
remote clients use OAuth2 tokens instead — see the `oauth2-token-auth` spec
linked above.

**`caelus` is therefore not a security boundary.** It bypasses the API
entirely and only runs inside the Caelus containers, so anyone who can invoke
it is already an operator with database access — there is no privilege for a
missing check to escalate. Where a command does scope by acting user (`build
list`, `list-releases`, `get-release`), that is for consistency with the REST
behavior and to keep output useful, not to enforce anything. A command that
omits such a check is not a vulnerability, and neither is one that adds it.

## Request Flow (How Work Actually Moves)

1. API or CLI receives a command.
2. Facade calls a service in `app/services/`.
3. Service validates input and persists desired state.
4. For deployment-changing operations, service enqueues a reconcile job.
5. Reconciler applies/deletes resources via provisioner adapters.
6. Deployment status and reconcile metadata are persisted back to DB.

## Per-Deployment Object Storage

Deployments of a product whose template enables object storage get a private
bucket and a dedicated access key on the shared Garage instance, provisioned
by the reconciler as part of the apply path. The ordering is load-bearing: the
Secret is written after the namespace exists and before Helm runs, and on
delete the key is revoked before the bucket's expiry rule is set, because a
key with write access can replace its own bucket's lifecycle configuration.
The secret access key never enters Helm values — merged values are logged in
full and persisted into the tenant's own namespace. The platform's
provisioning credential is scoped to the bucket and key operations, and its
blast radius — it can read back the secret of any access key it can see — is
stated in the spec rather than left to be discovered.

Spec: [deployment-object-storage](../openspec/specs/deployment-object-storage/spec.md),
[garage-bucket-provisioning](../openspec/specs/garage-bucket-provisioning/spec.md),
[object-storage-chart-contract](../openspec/specs/object-storage-chart-contract/spec.md) ·
Rationale:
[add-garage-object-store](../openspec/changes/archive/2026-08-12-add-garage-object-store/design.md),
[add-deployment-object-storage](../openspec/changes/archive/2026-08-17-add-deployment-object-storage/design.md)

## Per-Deployment Relational Storage

Deployments of a product whose template enables relational storage get their
own PostgreSQL database and login role on the shared tenant cluster — a
separate instance from `caelus-postgres`, deployed per Terraform workspace,
reached only through a PgBouncer pair. The reconciler writes
`<deployment.name>-database` into the tenant's namespace and the chart
consumes it with `envFrom`; the password never enters Helm values.
Provisioning revokes `PUBLIC`'s `CONNECT` grant and then reads the privilege
back, failing the provision if `PUBLIC` still holds it; the role is created
with every attribute negated, and session limits are re-applied on every
reconcile so a tenant's `RESET` does not survive one.

The database is bounded by the plan's `database_bytes` allowance — separate
from `storage_bytes`, and neither is derived from the other — and
`caelus db-worker` escalates usage through warning, read-only and
login-refusal states, re-asserting each on every evaluation. Deleting a
deployment revokes access and records a `purge_after` deadline; the db-worker's
purge tick is the only thing that destroys tenant data, and **no backups exist
that a tenant can reach** — an accidental `DROP TABLE` is unrecoverable for
them.

`GET /api/users/{user_id}/deployments/{deployment_id}/database` returns the
connection details together with quota state and usage. It is a read of what
already exists: nothing is provisioned, rotated, or re-evaluated by it.

Spec: [deployment-relational-storage](../openspec/specs/deployment-relational-storage/spec.md),
[tenant-database-cluster](../openspec/specs/tenant-database-cluster/spec.md),
[relational-storage-chart-contract](../openspec/specs/relational-storage-chart-contract/spec.md),
[plan-database-enforcement](../openspec/specs/plan-database-enforcement/spec.md),
[database-credentials-api](../openspec/specs/database-credentials-api/spec.md),
[database-housekeeping-worker](../openspec/specs/database-housekeeping-worker/spec.md) ·
Rationale:
[relational-storage](../openspec/changes/archive/2026-08-27-relational-storage/design.md),
[database-connection-details](../openspec/changes/archive/2026-08-29-database-connection-details/design.md)

## Deployment Vars (Runtime Configuration)

A **var** is one entry in a deployment's process environment. Vars are the
single channel into a pod's environment; `user_values_json` configures the
*chart*, not the process, and nothing fans one out into the other.
`deployment_var` is append-only history (a delete inserts a tombstone);
`release_var` binds each release to the var rows it was created with, which is
what makes a release reproducible after later writes and deletions. There is
no second schema: `x-caelus-target` on the one template schema routes a
property to the chart or to the environment (defaulting to `chart`), and a var
marked `x-caelus-sensitive` is write-only — reads omit the `value` entirely,
for everyone, and an absent `value` on write means "leave unchanged". Every
value is encrypted at rest under the keyring, sensitive or not.

Each applied release gets its own Secret (`{deployment}-vars-{number}`),
written before Helm runs and reaped after a successful apply; only the
Secret's name enters the values.

Spec: [deployment-vars-api](../openspec/specs/deployment-vars-api/spec.md),
[deployment-vars-data-model](../openspec/specs/deployment-vars-data-model/spec.md),
[deployment-vars-schema-routing](../openspec/specs/deployment-vars-schema-routing/spec.md),
[deployment-vars-reconciliation](../openspec/specs/deployment-vars-reconciliation/spec.md) ·
Rationale:
[deployment-vars](../openspec/changes/archive/2026-08-24-deployment-vars/design.md)

## API and CLI Parity

Parity is achieved by sharing service functions, not by duplicating logic.
Every REST route has a `caelus` equivalent; the CLI-only commands (`reconcile`,
`build-worker`, `catalog apply|curate|lint`) are operator and build tooling,
exempt from parity by design. The endpoint surface itself lives in the
capability specs the other sections of this README link, and the nested-route
conventions are in `AGENTS.md` § Conventions.

CLI output contract: successful command output on stdout is YAML-encoded
entity payloads (single object or list, mirroring REST JSON responses); logs
and errors are emitted on stderr. That makes the output pipeable:

```bash
caelus list-deployments | yq -y '.[] | {id, domainname, status}'
```

## Account SSH Keys

An SSH public key is owned by a **user**, never by a deployment; a user's keys
apply to every deployment that user owns, including ones created after the key
was registered. They are the SSH credential: the edge resolves every SFTP
connection against this table. Reads and deletes follow
`require_self`; **adds are owner-only even for administrators**, because
installing a key on someone's account is impersonation. A key is addressed by
its `SHA256:` fingerprint through a path-converter route — the only one in the
API, and not a stylistic choice: roughly half of all fingerprints contain a
`/`.

Spec: [ssh-key-api](../openspec/specs/ssh-key-api/spec.md),
[ssh-key-data-model](../openspec/specs/ssh-key-data-model/spec.md) · Rationale:
[account-ssh-keys](../openspec/changes/archive/2026-08-28-account-ssh-keys/design.md)

## The SSH Edge

`GET /api/ssh` publishes this environment's SSH edge — host, port, and the
public half of its host key, keyed by OpenSSH key type — publicly, and not
gated on any deployment: the key is a per-environment fact a client needs
before it knows which deployment to address, and an unconfigured key is
reported empty (refused, never trusted) rather than fabricated. The SFTP
credentials endpoint's availability check tracks what a deployment's chart
actually renders, so both access profiles report available rather than the
older profile's marker reporting no access for every deployment on the newer
one.

Spec: [ssh-edge-host-key](../openspec/specs/ssh-edge-host-key/spec.md),
[sftp-credentials-api](../openspec/specs/sftp-credentials-api/spec.md) ·
Rationale: [cli-ssh-access](../openspec/changes/archive/2026-09-02-cli-ssh-access/design.md)

## Product Catalog (Curated Products)

Products come in two kinds, and the difference is a single column, `curated`:
non-curated products are database-authored and fully editable; curated products
are declared in `products/catalog/<slug>.yaml`, applied on rollout, and
read-only through the API, CLI, and admin UI apart from `visibility`.
`CatalogReconciler` has exactly two verbs — insert and repoint — and never
mutates or deletes template rows, so the template table is an append-only
ledger and running deployments keep resolving their `applied_template_id`.
Only the reconciler writes `product.curated` and `product.slug`; file presence
is the sole carrier of curation, so releasing a product is deleting its
catalog file.

The catalog commands are operator and build tooling, CLI-only and exempt from
parity: `caelus catalog lint` validates files without a database (CI),
`apply` reconciles into the database (run by an init container on rollout),
and `curate` generates a catalog file from database state. Urgent intervention
accepts `?force=true` / `--force` on updates — never on deletion — and every
forced write is logged. The catalog directory is baked into the API image and
applied by a `catalog` init container after `migrate`; a malformed catalog
fails the rollout rather than serving stale products.

Spec: [product-catalog-format](../openspec/specs/product-catalog-format/spec.md),
[catalog-reconciliation](../openspec/specs/catalog-reconciliation/spec.md),
[catalog-cli](../openspec/specs/catalog-cli/spec.md),
[curated-product-governance](../openspec/specs/curated-product-governance/spec.md),
[product-visibility](../openspec/specs/product-visibility/spec.md) · Rationale:
[curated-product-catalog](../openspec/changes/archive/2026-08-03-curated-product-catalog/design.md)

## Product Icon and Static File Serving

### Static File Endpoint
- `GET /api/static/{path}` serves files from `STATIC_PATH` (configurable via `STATIC_PATH` env var, defaults to `./static`).
- Path traversal outside `STATIC_PATH` is blocked.
- Responses include `ETag` headers and support `If-None-Match` for `304 Not Modified`.
- Public access (no auth required).

### Product Icon Workflow
- **Create with icon**: `POST /api/products` accepts multipart form with:
  - `payload`: JSON object with product data (`name`, `description`, `template_id`)
  - `icon`: optional image file
- Atomic create: if icon processing fails, no product is persisted.
- Icon processing: decode, normalize orientation, center-crop to square, downscale to max 256x256, output PNG.
- Icon size limit: 10MB max.
- Resolution limit: 2048x2048 max source dimensions.
- Icon files are immutable and content-addressed: uploads are stored as content-hash files, and existing files remain.

### Icon Endpoints
- `PUT /api/products/{product_id}/icon`: Upload/replace icon for existing product.
- `GET /api/products/{product_id}/icon`: Returns `302` redirect to `/api/static/{rel_icon_path}` or `404` if no icon.

### Configuration
- `STATIC_PATH`: Root directory for static files (default: `./static` in dev, `/var/static` in production).
- Static files are served at `/api/static`.

## Core Data Model

The entities live in `app/models.py`. `User` is identified by `email` (unique
among non-deleted users) and soft-deletes. `Product` owns many
`ProductTemplateVersion` rows; `slug` and `curated` join a product to its
catalog file and are written only by `CatalogReconciler`. `Deployment` is
scoped to one user and carries stable runtime identity — `name` (Helm release,
max 27 chars) and `namespace` (K8s namespace, max 30 chars), both
DNS-label-safe and immutable — plus `desired_template_id` /
`applied_template_id` and `user_values_json`.

`DeploymentRelease` is the record of one rollout: created by the request that
asks for it, completed by the reconciler, numbered per deployment from 1, and
never revised after it is written — status is derived, never stored, and
liveness is the `applied_release_id` pointer. `DeploymentReconcileJob` is the
queue item (`queued -> running -> done|failed`), with one open job per
deployment and a worker lease whose expiry drives reclamation.

Spec: [deployment-release-ledger](../openspec/specs/deployment-release-ledger/spec.md),
[deployment-naming](../openspec/specs/deployment-naming/spec.md),
[deployment-namespace](../openspec/specs/deployment-namespace/spec.md),
[build-data-model](../openspec/specs/build-data-model/spec.md),
[deployment-vars-data-model](../openspec/specs/deployment-vars-data-model/spec.md),
[plan-data-model](../openspec/specs/plan-data-model/spec.md),
[subscription-data-model](../openspec/specs/subscription-data-model/spec.md),
[mollie-payment-data-model](../openspec/specs/mollie-payment-data-model/spec.md),
[ssh-key-data-model](../openspec/specs/ssh-key-data-model/spec.md) · Rationale:
[add-deployment-logs](../openspec/changes/archive/2026-08-18-add-deployment-logs/design.md)

## Critical Invariants

- Active user emails are unique (`deleted_at IS NULL` scoped uniqueness).
- An account subdomain, once claimed, belongs to that account permanently and
  is never claimable by another — the one uniqueness guarantee here that spans
  deleted rows as well as active ones. Certificate transparency has already
  published the name, so releasing it would hand a stranger the traffic, links
  and DNS caches of the previous holder. Enforced in two places, because
  neither covers the other: `uq_user_subdomain_active` is partial
  (`deleted_at IS NULL`, mirroring `uq_user_active` for email) and so only
  constrains live rows, while the claim check queries the column unfiltered
  and is what refuses a deleted account's label.
- Active product names are unique (`deleted_at IS NULL` scoped uniqueness).
- Active product slugs are unique (`deleted_at IS NULL` scoped uniqueness).
- `product.slug` and `product.curated` are written only by `CatalogReconciler`;
  no REST endpoint, CLI command, or UI action sets them, including under
  `--force`. Catalog file presence is the single source of truth for curation.
- `product_template_version` is append-only with respect to the reconciler: it
  inserts and repoints, never updates spec fields and never soft-deletes.
- Active template `(chart_ref, chart_version, product_id)` combinations are
  unique.
- Only one open reconcile job (`queued` or `running`) may exist per deployment.
- Domain names are unique for deployments that are not in `deleted` status.
- Deployment identity requires DNS-safe `name` (max 27 chars) and `namespace`
  (max 30 chars). Active deployments have a unique `(namespace, name)` pair.
- Kubernetes namespace is `deployment.namespace`; Helm release name is
  `deployment.name`.

## Deployment Lifecycle and State Transitions

Create validates user + template + user values, derives the persisted
`domainname` from the template schema, generates `name` and `namespace`, and
enqueues a `create` job. Update (upgrade) allows only forward template changes
within the same product lineage, from `ready` or `error`. Delete marks
`deleting` and is idempotent; `GET` on a deleted deployment returns `404`. The
apply path ends `ready` with `applied_template_id = desired_template_id`; the
delete path ends `deleted`; failure stores `error` and `last_error`.

Spec: [deployment-create-contract](../openspec/specs/deployment-create-contract/spec.md),
[deployment-payment-states](../openspec/specs/deployment-payment-states/spec.md),
[deployment-release-api](../openspec/specs/deployment-release-api/spec.md)

## The Account Domain Name

Every account holds one permanent DNS label, and every application it deploys
is addressed beneath it at `<app>.<subdomain>.<domain>`. It is claimed once
through its own resource and is never changed, released, or transferred — not
by any endpoint, not on account deletion.

Spec: [account-subdomain-record](../openspec/specs/account-subdomain-record/spec.md),
[hostname-validation](../openspec/specs/hostname-validation/spec.md),
[deployment-create-contract](../openspec/specs/deployment-create-contract/spec.md) ·
Rationale:
[account-subdomain-claim](../openspec/changes/archive/2026-09-09-account-subdomain-claim/design.md)

## Per-Account TLS

Every account holds one wildcard certificate covering every hostname its
applications will ever be addressed at, and a DNS record that keeps those
hostnames resolving. Both are provisioned by the reconcile, before the Helm
release, and neither is ever deleted. Nothing copies certificate material
anywhere: the certificate is added to the ingress controller's certificate
store, which serves it to routes in namespaces that never reference it.

A deployment whose account holds no certificate does not complete. The
reconcile defers — the deployment stays `provisioning` and its job returns to
the queue — until the certificate is issued, and fails the deployment when the
waiting budget runs out. That is the terminal behavior, not a placeholder.

Spec: [account-dns-record](../openspec/specs/account-dns-record/spec.md),
[account-tls-certificate](../openspec/specs/account-tls-certificate/spec.md),
[platform-tls-store](../openspec/specs/platform-tls-store/spec.md) ·
Rationale:
[per-user-tls-certificates](../openspec/changes/archive/2026-09-08-per-user-tls-certificates/design.md)

## Reconcile Queue Semantics

- Enqueue runs inside same transaction as deployment mutation.
- Claiming uses `FOR UPDATE SKIP LOCKED`.
- Guarantees no double claim for the same job under parallel workers, covered
  by `test_claim_next_job_never_double_claims_under_parallel_workers` (sixteen
  threads against eight jobs).
- A job is claimable when it is `queued` and due (`run_after <= now`), **or**
  when it is still `running` but its lease has expired.

### Lease expiry

A worker that dies mid-reconcile (pod restart, OOM kill, node eviction) leaves
its job at `running` with `locked_by` naming a process that never returns.
Without a lease that job is never retried and its deployment stays in
`provisioning`/`deleting` forever, holding its hostname against re-creation.

- Lease length: `CAELUS_RECONCILE_JOB_LEASE_SECONDS`, default `600` (10 min).
  Never set this below `HELM_TIMEOUT_SEC` (300s): a healthy worker may
  legitimately spend the whole Helm budget inside one reconcile, and a shorter
  lease would let a second worker steal a live job.
- Reclaims bump `attempt` and log at WARNING with the previous `locked_by` /
  `locked_at`; grep worker logs for `Reclaimed expired reconcile job lease`.
- Reclaims are not capped: only a completed reconcile can move a deployment out
  of `provisioning`/`deleting`, so retries continue (once per lease interval)
  until the job reaches `done` or `failed`.
- `mark_job_done` / `mark_job_failed` take an optional `worker_id`; when given,
  the write is conditional on the job still being leased to that worker, so a
  wedged worker that wakes up late cannot overwrite the new owner's result.
- `defer_job` returns the **same** row to `queued` with a later `run_after`,
  for work that is unfinished rather than done or failed — a reconcile waiting
  for its account's certificate. The same row because one open job per
  deployment is a constraint, and `attempt` is left alone because it counts
  lease expiries, which a deferral is not.

## Builds (Project Archive → Container Image)

A build turns a user's project directory into a digest-pinned container image
in the internal registry. Builds belong to a **user**, never to a deployment:
most products build nothing, a single deployment may consume several images,
and **nothing here triggers a rollout** — the client takes a successful
build's `image` and submits it to the deployment update endpoint itself.

Uploads never pass through the API: the client mints a presigned-POST slot
(`POST /api/artifacts`), uploads the archive straight to object storage, and
confirms with `POST /api/users/{uid}/builds` — `caelus build submit <dir>`
does all three phases in one command. The state machine is
`queued → running → succeeded | failed`; a failed build is never retried
automatically. On success the build exposes `image` as
`{user_id}@sha256:<64 hex>` — the registry host stripped, which is what stops
a tenant pointing a deployment at an arbitrary registry. The log endpoint
serves the stored `bytea` with HTTP Range and an `X-Build-Status` header on
every response, capped at 10 MiB.

The build worker (`caelus build-worker`) runs one repeating non-blocking
pass: advance every running build, then claim queued builds while below
`CAELUS_BUILD_MAX_IN_FLIGHT`. The build container holds no platform
credentials and reports its result through the pod's termination message.

The layer cache (one repository per owner per environment), the ghcr.io
mirror, and the node prerequisites (a rebuilt node fails at two separate
points) are operational: the reasoning and the failure modes live in
[`products/custom/builder/README.md`](../products/custom/builder/README.md).

Spec: [build-api](../openspec/specs/build-api/spec.md),
[build-artifact-upload](../openspec/specs/build-artifact-upload/spec.md),
[build-data-model](../openspec/specs/build-data-model/spec.md),
[build-execution](../openspec/specs/build-execution/spec.md),
[build-worker](../openspec/specs/build-worker/spec.md) · Rationale:
[add-build-subsystem](../openspec/changes/archive/2026-08-14-add-build-subsystem/design.md)

## Provisioning Boundary

`app/provisioner.py` is the boundary to external systems.

- `KubeAdapter`: namespace existence/create/delete via `kubectl`.
- `HelmAdapter`: install/upgrade/uninstall/status via `helm`.
- `Provisioner`: facade used by reconciler.

Important:
- Command execution is centralized in `app/proc.py`.
- Adapter errors are normalized into `AdapterCommandError` with truncated detail.

## Values and Schema Rules

User-editable values are intentionally scoped under `values.user.*`.

Rules enforced by `app/services/template_values.py`:
- `user_values_json` must be an object.
- If user values are provided, template schema must define `properties.user`.
- Final Helm values are merged as `defaults` + `{ "user": user_values }` +
  `system_overrides`.
- Final merged object is validated against full template schema.

## Error Handling

Domain exceptions live in `app/services/errors.py`:
- `IntegrityException` -> HTTP 409
- `DeploymentInProgressException` -> HTTP 409
- `NotFoundException` -> HTTP 404

FastAPI exception mapping is registered in `app/api/utils.py`.
CLI catches domain exceptions and exits with code `1`.

## Logging

- Shared logging setup: `app/logging_config.py`.
- Configured at API and CLI entrypoints.
- Colorized levels on TTY (disabled if `NO_COLOR` is set).
- Level control via `CAELUS_LOG_LEVEL` (default `INFO`).
- High-signal logs cover external commands and provisioning actions.
- High-signal logs cover reconcile start/fail/finish.
- High-signal logs cover job queue operations.
- High-signal logs cover deployment mutation side effects.

## Local Development

From `api/`:

- Install deps: `uv sync`
- Run API: `uv run python3 app/main.py`
- Run CLI help: `uv run caelus --help`
- Run tests: `uv run pytest`

Docs UI:
- `GET /` redirects to `/docs`.

## Database and Migrations

- Runtime DB URL: `CAELUS_DATABASE_URL`. Postgres is the only supported
  database — in production, in dev, and under test.
- Schema comes from Alembic, always. There is no `create_all` helper: the test
  suite migrates its database with the real chain, so drift between the models
  and the migrations fails the suite instead of hiding.
- Alembic config: `alembic.ini`, scripts in `alembic/versions/`.

Migration commands:
- New migration: `alembic revision --autogenerate -m "message"`
- Upgrade DB: `alembic upgrade head`

## Testing Strategy

### Running the suite

The suite runs against a real PostgreSQL database. Inside the devcontainer
everything is already in place — `docker-compose.yml` sets
`CAELUS_TEST_DATABASE_URL` and the compose `postgres` service is running, so
`uv run --no-sync pytest` is all it takes.

Outside the devcontainer, start a Postgres and point the suite at it:

```bash
docker compose up -d postgres
export CAELUS_TEST_DATABASE_URL=postgresql+psycopg://caelus:caelus@localhost:5432/caelus_test
cd api && uv run --no-sync pytest
```

The connecting user must hold `CREATEDB` (or be a superuser): `conftest.py`
creates the test database itself if it is missing, migrates it with
`alembic upgrade head`, and resets it between tests — which also needs
`session_replication_role`, a superuser setting. The compose image's `caelus`
user is a superuser, so dev and CI are both covered.

There is no in-memory or SQLite mode. A run without a reachable Postgres fails
with an explanatory error rather than skipping tests or reporting a false pass.
The test database is separate from the dev `caelus` database and is wiped
constantly, so never point the variable at a database you care about.

Test execution is serial: one shared test database, one cleaner. `pytest-xdist`
is not supported as-is.

### What lives where

- `tests/test_api.py`: REST behavior and validation.
- `tests/test_cli.py`: CLI parity and error handling.
- `tests/test_deployments.py`: deployment mutation semantics.
- `tests/test_reconcile_service.py`: reconcile state transitions.
- `tests/test_jobs_service.py`: queue/claim/mark semantics, including
  concurrent claiming under sixteen parallel workers.
- `tests/test_deployment_release_ledger.py`: the deferred foreign keys between
  `deployment` and `deployment_release`, checked at COMMIT.
- `tests/test_schema_drift.py`: the migration chain and the models must
  describe the same schema.
- `tests/test_platform_adapters.py`: Kubernetes/Helm adapter behavior.

## Conventions for Contributors

- Keep API + CLI features in parity.
- Put business logic in `app/services/`; keep facades thin.
- Add/adjust tests for any behavior change.
- Keep ownership scopes explicit in routes and queries.
- Prefer stable domain errors over ad hoc exceptions.
- Update migrations when schema changes.

## Known Gaps and Current TODOs

- Namespace lifecycle is still exposed on `Provisioner`; intended direction is to
  make install/uninstall manage namespaces transparently.
- API create-deployment route has a TODO note to tighten product/template scope
  validation at facade level (service already validates template existence).

## First 30 Minutes for a New Agent

1. Read `app/models.py` to understand entities and constraints.
2. Read `app/services/deployments.py`, `jobs.py`, `reconcile.py` in that order.
3. Skim `app/provisioner.py` and `app/proc.py` for external-system behavior.
4. Run `pytest` and inspect failing tests if any.
5. For feature work, implement in services first, then expose in both API and CLI.
