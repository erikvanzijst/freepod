# Agent Instructions

This repository is a monorepo with:
- `api/`: FastAPI + SQLModel service with a Typer CLI for provisioning.
- `ui/`: React + TypeScript + MUI frontend for the API.
- `tf/`: Terraform infrastructure for deploying to Kubernetes.

## Project Goals
- Provision user-owned webapp instances on Kubernetes (pods, PVCs, ingress).
- Provide a REST API and CLI that are functionally identical.
- Model products, template versions, users, and deployments with clear ownership.

## Architecture Notes
- API and CLI are thin facades over services in `api/app/services/`.
- **Two different things are called "the CLI".** `caelus` (`api/app/cli.py`) is
  the *operator* tool: it runs in-process against the database and services, and
  every reference to "CLI" elsewhere in this file means that one. `freepod`
  (`cli/`) is the *end-user client*: a separately installable package that talks
  to a deployed platform over HTTP, imports nothing from `api/`, and shares no
  code with it.
- Provisioning is in `api/app/provisioner.py`: a `Provisioner` that drives
  kubectl and helm through adapters (namespaces, tenant network policy,
  secrets, Helm releases).
- **Builds** turn an uploaded project archive into a container image and are
  owned by a **user**, addressed under their owner like every other user-owned
  resource. Nothing auto-deploys a build — the client submits a successful
  build's `image` to the deployment create/update endpoint itself, and may pass
  that build's `build_id` alongside it, which is recorded on the release row.
  Spec: [build-api](openspec/specs/build-api/spec.md),
  [build-data-model](openspec/specs/build-data-model/spec.md),
  [build-execution](openspec/specs/build-execution/spec.md),
  [build-worker](openspec/specs/build-worker/spec.md) · Rationale:
  [add-build-subsystem](openspec/changes/archive/2026-08-14-add-build-subsystem/design.md),
  [add-deployment-logs](openspec/changes/archive/2026-08-18-add-deployment-logs/design.md)
- **Three worker processes.** `caelus worker` (reconcile queue), `caelus
  build-worker` (builds), and `caelus db-worker` (tenant-database housekeeping:
  quota measurement, purging deleted deployments' databases after their grace
  period, reclaiming orphaned cluster objects). Spec:
  [worker-process-pool](openspec/specs/worker-process-pool/spec.md),
  [build-worker](openspec/specs/build-worker/spec.md),
  [database-housekeeping-worker](openspec/specs/database-housekeeping-worker/spec.md)
- **Account SSH keys are the SSH credential.** A user registers SSH public keys
  on their account; they are owned by the user, scoped to no deployment, and are
  what authenticates every SSH connection. Adds are owner-only even for
  administrators, and a key is addressed by its `SHA256:` fingerprint. Spec:
  [ssh-key-api](openspec/specs/ssh-key-api/spec.md),
  [ssh-key-data-model](openspec/specs/ssh-key-data-model/spec.md) · Rationale:
  [account-ssh-keys](openspec/changes/archive/2026-08-28-account-ssh-keys/design.md)
- **SSH routing and authentication are resolved per connection.** The edge
  (sshpiperd) asks the SSH auth resolver — `ssh-auth/`, a gRPC plugin — rather
  than reading cluster objects, so the reconciler owns nothing for this feature.
  Spec: [sftp-edge-routing](openspec/specs/sftp-edge-routing/spec.md),
  [ssh-chart-contract](openspec/specs/ssh-chart-contract/spec.md),
  [ssh-auth-resolver](openspec/specs/ssh-auth-resolver/spec.md) · Rationale:
  [ssh-grpc-auth-plugin](openspec/changes/archive/2026-08-30-ssh-grpc-auth-plugin/design.md),
  [ssh-auth](ssh-auth/README.md)
- **One SSH sidecar for every product, and a product declares one thing: its
  session root.** The `ssh-sidecar` library chart
  (`products/_lib/ssh-sidecar-chart`) renders the platform's own image
  (`products/_lib/ssh-sidecar-image`) for every deployment that has SSH access
  at all. `volume:/<path>` roots a session at a read-only mount of the data the
  product exposes; `app-container` roots it at the filesystem the tenant's code
  runs in. **The six data-bearing products declare a volume root; `custom`
  declares `app-container`**, and a product that declares nothing renders no
  sidecar and is not routable. Spec:
  [ssh-chart-contract](openspec/specs/ssh-chart-contract/spec.md),
  [ssh-sidecar-image](openspec/specs/ssh-sidecar-image/spec.md),
  [ssh-session-dispatcher](openspec/specs/ssh-session-dispatcher/spec.md) ·
  Rationale:
  [unified-ssh-sidecar](openspec/changes/archive/2026-09-03-unified-ssh-sidecar/design.md)
- **The `-ssh` Service naming convention is shared between the charts and the
  resolver, and neither may change it alone.** The edge derives a deployment's
  upstream address as `<release>-ssh.<namespace>.svc` by string convention; that
  is the name every product chart renders. The coupling is invisible from both
  sides — the resolver never validates the Service, and nothing in a chart's own
  release consults it — so a unilateral change produces deployments that
  authenticate and then reach nothing. `ssh-auth/convention_test.go` renders
  both session roots and asserts the two agree; it is the only thing that fails
  when one side moves. Moving it costs a maintenance window with the fleet
  unroutable in between.
- **Vars are the single channel into a pod's environment.** A deployment's
  `vars` become environment variables in its container;
  `deployment.user_values_json` configures the **chart**, not the process, and
  nothing fans one out into the other. Which channel a property takes is a
  marker on the one template schema (`x-caelus-target`); a var marked
  `x-caelus-sensitive` is write-only. Spec:
  [deployment-vars-api](openspec/specs/deployment-vars-api/spec.md),
  [deployment-vars-data-model](openspec/specs/deployment-vars-data-model/spec.md),
  [deployment-vars-schema-routing](openspec/specs/deployment-vars-schema-routing/spec.md),
  [deployment-vars-reconciliation](openspec/specs/deployment-vars-reconciliation/spec.md) ·
  Rationale: [deployment-vars](openspec/changes/archive/2026-08-24-deployment-vars/design.md)
- **A deployment's database credentials are not vars.** The database password
  is platform-held and reaches the pod through a Kubernetes Secret the
  reconciler publishes; Helm values carry references only. Spec:
  [deployment-relational-storage](openspec/specs/deployment-relational-storage/spec.md),
  [tenant-database-cluster](openspec/specs/tenant-database-cluster/spec.md) ·
  Rationale: [relational-storage](openspec/changes/archive/2026-08-27-relational-storage/design.md)
- **Encrypted columns and the keyring.** Var values and database passwords are
  encrypted under one rotatable keyring; every encrypted column is declared in
  one registry, the API and `caelus worker` refuse to start when their keyring
  cannot cover what is stored, and `caelus db-worker` deliberately does not.
  `caelus keyring-rotate` re-encrypts every registered column — adding a new
  encrypted column means adding it to the registry, or a retired key strands it
  silently. Spec:
  [deployment-vars-data-model](openspec/specs/deployment-vars-data-model/spec.md)
  · Rationale:
  [relational-storage](openspec/changes/archive/2026-08-27-relational-storage/design.md)
- **Every account holds one wildcard certificate and one DNS record**, covering
  every hostname its applications will ever have. Both are provisioned by the
  reconcile before the Helm release and neither is ever deleted; a deployment
  whose account has no certificate defers rather than completing, and fails
  when the wait runs out. Nothing copies certificate material: the certificate
  joins the ingress controller's store, which serves it to routes in namespaces
  that never reference it. The store, the platform wildcard and every account
  certificate are **cluster singletons shared by dev and prod**, so a change to
  them is never environment-scoped. Spec:
  [account-dns-record](openspec/specs/account-dns-record/spec.md),
  [account-tls-certificate](openspec/specs/account-tls-certificate/spec.md),
  [platform-tls-store](openspec/specs/platform-tls-store/spec.md) · Rationale:
  [per-user-tls-certificates](openspec/changes/per-user-tls-certificates/design.md)
- Products are either **curated** (declared in `products/catalog/<slug>.yaml`,
  reconciled into the database on rollout, and read-only through the API, CLI,
  and admin UI apart from `visibility`) or **non-curated** (database-authored).
  Only `CatalogReconciler` writes `product.curated` and `product.slug`. Spec:
  [product-catalog-format](openspec/specs/product-catalog-format/spec.md),
  [catalog-reconciliation](openspec/specs/catalog-reconciliation/spec.md),
  [curated-product-governance](openspec/specs/curated-product-governance/spec.md) ·
  Rationale:
  [curated-product-catalog](openspec/changes/archive/2026-08-03-curated-product-catalog/design.md)
- Authentication: all API endpoints require the `X-Auth-Request-Email` header
  (injected by oauth2-proxy in production, set by the frontend in local dev);
  `GET /api/me` is the session initialization endpoint. The CLI uses
  `CAELUS_USER_EMAIL` with an optional `--as-user` override. Spec:
  [auth-header-integration](openspec/specs/auth-header-integration/spec.md),
  [user-endpoint-authorization](openspec/specs/user-endpoint-authorization/spec.md)

## Quick Start
Each project owns its own `.venv`, which uv resolves from the working
directory. There is no shared environment: run tooling through `uv run` from
the directory it belongs to.

### API (`api/`)
- `cd api/`
- Install deps: `uv sync`
- Run API: `uv run --no-sync uvicorn app.main:app --reload`
- Run CLI: `uv run --no-sync python -m app.cli --help`
- Tests: `uv run --no-sync pytest`
For details, see `api/README.md`.

### Client CLI (`cli/`)
- `cd cli/`
- Install deps: `uv sync`
- Run: `uv run freepod --help`
- Tests: `uv run pytest`
Targets the environment recorded in `.freepod.json` when run from a project,
and `prod` otherwise. `--env dev` overrides both; `FREEPOD_ENV=dev` only moves
the default for directories that hold no project, so it cannot pull a command
away from the environment its project lives on. For details, see
`cli/DEVELOPMENT.md` — the invariants, the platform contracts, and the
reasoning. `cli/README.md` is the package's PyPI landing page, written for end
users; keep internals out of it.

Published to PyPI as `freepod`, on its own release cadence: bump
`__version__` in `cli/src/freepod/__init__.py` — the single source, which
`pyproject.toml` reads through Hatch — and push a `freepod-v*` tag. No commit
to `master` publishes the client. See `cli/DEVELOPMENT.md` § CI and releasing.

### UI (`ui/`)
- `cd ui/`
- Install deps: `npm install`
- Run UI: `npm run dev`
- Build: `npm run build`
For details, see `ui/README.md`.

### Terraform (`tf/`)

The Terraform infrastructure is split into two independent root modules:

- `tf/app/`: Caelus application resources (API, UI, worker, OAuth2-proxy,
  Postgres). Uses Terraform workspaces for dev (`default`) and prod (`prod`)
  environment separation.
- `tf/deps/`: Shared singleton dependencies (Keycloak, Echo, monitoring, and
  Garage — the S3 object store at `blob.freepod.eu`). No workspaces;
  single instance shared across all environments.

Both deploy to the same k3s cluster. Deploy `tf/deps/` first, then
`tf/app/`. Each has its own `secrets.auto.tfvars` (gitignored).

For details, see `tf/README.md`, `tf/app/README.md`, `tf/deps/README.md`.

## Conventions
- Keep CLI and REST functionality in lockstep. **Exception**: the `caelus
  catalog` command group (`apply`, `curate`, `lint`), the long-running worker
  entry points (`caelus worker`, `caelus build-worker`, `caelus db-worker`),
  and `caelus keyring-rotate` are intentionally CLI-only and require no REST
  equivalent. These are operator and build tooling rather than tenant-facing
  surface — `catalog apply` is invoked by an init container during rollout,
  `lint` runs in CI with no database, the workers are processes rather than
  requests, and `keyring-rotate` is a maintenance sweep an operator runs while
  rotating an encryption key. The write guards they depend on live in
  `api/app/services/`, so REST, CLI, and the admin UI still enforce identical
  rules and no parity gap is introduced.
- Put all DB/ORM logic in `api/app/services/` and call from API + CLI (DRY).
- Build logs are stored as `bytea`, not text, and served as raw bytes:
  container output is tenant-controlled and may contain invalid UTF-8 or NUL
  bytes, which Postgres `text` cannot store at all. Do not decode it on the
  way in or out.
- Prefer nested routes:
  - Templates under products: `/products/{product_id}/templates`
  - SSH keys under users: `/users/{user_id}/ssh-keys`, one key addressed by its
    `SHA256:` fingerprint as a **path-converter** segment
  - Deployments under users: `/users/{user_id}/deployments`
  - Releases under deployments:
    `/users/{user_id}/deployments/{deployment_id}/releases`, addressed by the
    per-deployment release **number** rather than the `uuid4`
  - Builds under users: `/users/{user_id}/builds`
  - Vars under deployments, by **phase** and key:
    `/users/{user_id}/deployments/{deployment_id}/vars/{phase}[/{key}]`. The
    phase (`runtime`, the only one so far) is a path segment because it is part
    of a var's identity, not a filter over a set — and it is a phase, never an
    environment: a staging app is its own deployment.
- Git worktrees live at /workspace/trees/<branch-name>. Create with:
  `git worktree add /workspace/trees/<name> -b <name>`.

## Documentation Layering

OpenSpec is the source of truth for behavior and for the reasoning behind it.
Prose docs point at it; they do not restate it.

- `openspec/specs/<capability>/spec.md` — **what must be true**. Requirements
  and scenarios. Normative.
- `openspec/changes/archive/<date>-<slug>/design.md` — **why it is that way**:
  the decision, the alternatives weighed, the measurements. Archive paths are
  dated and immutable, so link them directly.
- READMEs and `cli/DEVELOPMENT.md` — **how to work with the code today**: how
  to run, test and operate it, the codebase map, troubleshooting, and
  narrative that spans several capabilities.

Capability directories under `openspec/specs/` are not immutable the way
archive paths are: `openspec sync` can rename or merge them. Renaming or
merging a capability directory is a link-breaking operation — update the prose
links pointing at it in the same change.

When a feature was built through an OpenSpec change, its entry in a prose doc
is a terse orientation — a few sentences, enough that a reader knows the
feature exists and roughly what shape it has — followed by links:

````markdown
### Account SSH Keys

A user registers SSH public keys on their account. They are owned by the user
and scoped to no deployment; nothing consumes them yet.

Spec: [ssh-key-api](../openspec/specs/ssh-key-api/spec.md),
[ssh-key-data-model](../openspec/specs/ssh-key-data-model/spec.md) ·
Rationale: [account-ssh-keys](../openspec/changes/archive/2026-08-28-account-ssh-keys/design.md)
````

Do not restate requirements, endpoint tables, field lists, validation rules,
state transitions, error codes, or decision rationale that a linked document
already carries. If the linked document is wrong or unclear, fix it there.
A second copy is not a workaround, it is the failure mode this rule exists to
prevent: two texts that drift until neither can be trusted.

Anything that genuinely belongs in prose and nowhere else gets said once, in
one file, with the others linking to it.

Inline comments follow the same rule. Comment what the code does when that is
not obvious; cite the decision (`# D6`, or the capability name) instead of
re-explaining it. The design document holds the argument.

## Database & Migrations
- Migrations: Alembic in `api/alembic/` with `alembic.ini`.

## Testing
- API tests use FastAPI `TestClient` against a real Postgres database that
  `tests/conftest.py` creates and migrates with the Alembic chain, then
  empties before every test. It needs `CAELUS_TEST_DATABASE_URL` (already
  set by `docker-compose.yml`) and a user holding `CREATEDB`; a run without
  a reachable Postgres fails rather than skipping. See `api/README.md`
  § Testing.
- CLI tests use `typer.testing.CliRunner`.
- UI uses Vite with Vitest + Testing Library (`cd ui && npm test`).

## Quality
- Validate inputs; return stable errors. When several conditions share a status
  code, give the exception a `code` and let `app/api/util.py` emit it, so
  clients branch on an identifier rather than on prose. Anything without one
  keeps the plain `{"detail": ...}` body.
- Write tests for all new behavior.
- No secrets in code.

## Comments
Do NOT add explanatory inline comments to code. Only comment on non-obvious 'why', never 'what'.
Never duplicate a docstring or restate the line below it. If you find yourself writing a comment
for a self-evident line, delete it.

## Commit Messages
- Follow standard Git commit message style:
  - Short imperative subject line, followed by an empty line.
  - Wrap all lines at 78 characters max.
- **Quote the whole command** – wrap the entire `git commit` call in single quotes (or use `-F <file>`).
  ```bash
  git commit -m 'subject line' -m $'body line 1\nbody line 2…'
  ```
- **Escape back‑ticks/quotes** – never place unescaped `` ` `` or " " inside a `-m` argument; use `\\` or `$'…'` quoting.
- **Check exit status** – after `git commit …` verify `$? == 0`; on error abort and report before retrying.
- Explain why and what changed in the body.

## UI Conventions
- Extract React components into focused, single-responsibility files under
  `ui/src/components/`. Avoid inlining complex functionality into page-level
  components (`Dashboard.tsx`, `Admin.tsx`).
- Form field components with specialized behavior (e.g., `HostnameField`)
  should be their own component files, not inlined into the form.
- Schema-driven fields in `UserValuesForm` can be overridden by matching on
  `field.title` (case-insensitive) and rendering a custom component instead
  of the default `<TextField>`.
- `UserValuesForm` partitions its submission by each field's `target`:
  chart values through `onChange`, runtime vars through `onVarsChange`. A
  sensitive field renders empty and submits **no entry at all** when untouched
  — an empty string is a real value and would wipe the stored secret.

## Contribution Checklist
- Update or add tests for new behavior.
- Keep API + `caelus` CLI parity (same features and validations).
- Extract a UI component before duplicating it. `SectionSidebar` and
  `CopyButton` exist because a second copy was about to.
- When an API contract changes, check whether `freepod` (`cli/`) depends on it.
  It ships on its own cadence, so it must learn values from the platform at
  runtime rather than embedding them — a constant baked into the client is
  wrong the first time the platform retunes it.
- Update migrations for schema changes.
- When behavior changes, the spec is the update that matters. Touch
  api/README.md, ui/README.md, cli/DEVELOPMENT.md, tf/README.md or AGENTS.md
  only when the *workflow* changes — how to run, build, test or operate the
  thing — or to add a new capability's terse entry and links per
  § Documentation Layering. Prose that restates a spec is a regression, not a
  doc update. `cli/README.md` changes only when the end-user surface does — it
  ships to PyPI as the package's landing page.
