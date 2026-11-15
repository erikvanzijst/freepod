# Design

## Context

See proposal.md for the motivation. The current state this design builds on:

- `freepod deploy` already creates the deployment before it builds (`ensure_deployment`),
  with no image, so the `custom` chart serves its placeholder pod. Init creates nothing.
- The first reconcile of a new deployment takes minutes. An update that releases is
  refused until the deployment is `ready` or `error`, so `release()` already waits with
  `wait_until_settled`, and the build usually overlaps the provisioning. Var writes are
  accepted in every status but `deleting`.
- `PUT /deployments/{id}` (`DeploymentUpdate`) takes the complete chart values, the
  template, an optional build and vars, and every accepted update creates a release, two
  byte-identical updates included (deployment-release-ledger). It validates the values
  against the template's chart projection and refuses runtime keys. Every shipped chart
  projection is closed, so an undeclared key is refused there.
- The platform treats `image` as a value of the `custom` chart, not a platform concept
  (`services/deployments.py`, `_validate_build_reference`). Only the `freepod` client
  knows the key (`IMAGE_KEY`), and it checks that the template declares it.
- `deployment.name` is the Helm release name. It prefixes the Secrets
  (`{name}-database`, `{name}-vars-N`, …) and labels, and `daemons/ssh-auth` reads it in
  raw SQL (`d.name || '-ssh.' || d.namespace`) to find the sidecar. `daemons/app-auth`
  brands its sign-in pages from `product.name`/`rel_icon_path`, under column-level
  grants in `tf/app/caelus/app-auth-bootstrap.sql`.
- Auth settings shown on the dashboard come from the database. `app_access._serving`
  merges the applied release's `values_json` with the template's system values. No field
  of a deployment read touches Kubernetes, and none will here.

## Goals / Non-Goals

**Goals:**

- `freepod init` stays quick: it claims the deployment and returns, and never waits on a
  reconcile.
- One generic identity model for every product. Custom stays an ordinary catalog product.
- One write endpoint for every client. The project file is the developer's interface to
  the deployment and the server is the source of truth, with no hidden state kept to
  reconcile the two.
- The platform learns nothing about any one chart's properties.

**Non-Goals:**

- Vars in the project file. They stay in `freepod var`. A later change could admit
  declared, non-sensitive runtime keys.
- A GitHub integration. This change only removes what stood in its way: server-side
  creation, and ownership the server records.
- Changing hostname routing, the release name formula, or how namespaces are named.
- Making an un-built deployment cheaper than its placeholder pod. Doing that without
  teaching the platform which chart value is Custom's image is a larger change, and the
  pod is billed like any other.
- Pulling the icon from the running app's favicon.

## Decisions

### D1. The owner's name is a new column. The release name keeps `name`.

The owner-chosen name goes in a new `display_name` column, which the API reports as
`name`. The `name` column keeps the generated release name, unchanged and unreported.
Nothing that reads the release name moves: not the reconciler, the Secrets and labels,
nor `ssh-auth`'s raw SQL. So the change needs no expand/contract rollout and no
`ssh-auth` release.

`display_name` is NOT NULL, backfilled per deployment-identity, with
`UNIQUE (user_id, lower(display_name)) WHERE status <> 'deleted'`. The same migration
adds `description`, `rel_icon_path`, `icon_source_sha256` and `managed_fields`.

*Alternative:* rename the column to `release_name` and reuse `name` for the display name.
That reads better in SQL, but `ssh-auth` reads the column directly, so it needs an
expand and a contract migration with an `ssh-auth` rollout gated between them.

### D2. Identity lives in columns on `deployment`, never in user values

Name, description and icon are not chart inputs. Putting them in `user_values_json`
would version them in the release ledger, make a rename cut a release and queue a
reconcile, and mix them into schema validation. As columns, renames are row updates.
Product values are the fallback, resolved by readers: the UI uses the product in the
read's template, and app-auth's query uses `coalesce`. The read reports only the
deployment's own values, so the UI can tell "own icon" from "inherited".

### D3. One write endpoint, which releases only when the running app would change

The existing `PUT /deployments/{id}` gains optional `name`, `description`, `icon` and
`managed_fields`, and `desired_template_id` becomes optional. Create accepts the same
fields. The dashboard, the operator CLI, `freepod apply` and `freepod deploy` all write
through it.

An update releases when its chart values differ from the stored ones, when it names
another template or a build, when it carries vars or vars are pending, or when the
deployment is in `error`. Anything else is a row update: no release, no reconcile, and no
`ready` guard, so a rename works while provisioning. Keeping `error` as an
always-release case means re-sending an unchanged update still retries a failed
deployment, which is the one use of identical updates today.

*Alternative:* a separate `PUT …/project` endpoint for the project file. It would overlap
the update in values, templates, builds and releases, and differ from it only in
ownership, which an explicit field expresses (D4).

### D4. Managed fields: an explicit list in the request

`managed_fields` is a JSON array of top-level keys. A request that carries it sets the
list and may change any field. A request without it may not change a managed field's
value (`409 managed_by_project_file`), and passes when it sends managed values unchanged,
as the dashboard does when it re-sends every chart value. Taking a field over is an
update with the list minus that key, so it needs no endpoint of its own.

The client states the list because only it knows which keys came from the file. `freepod`
sends the complete chart values (the file's keys over the stored ones) plus the build's
image, so "every key a CLI request carries" would claim all of them. Telling clients
apart by user agent has the same flaw, and it would not cover agents calling the API
directly or a future server-side reader of the file.

The server stores neither the file nor the values it last sent. The values live in their
real columns and in `user_values_json`. With enforcement on the server there is no
conflict to detect: the only path to divergence is an explicit take-over. Ownership is
per top-level key, and a managed key replaces its whole value. Ownership at the leaves
would need merge rules for arrays (`auth.public`) and partial objects, with no gain a
developer would notice.

This is not a security boundary. It is the owner's deployment, and the owner can take
over any field. It keeps the file and the dashboard from drifting apart by accident.

### D5. The client splits the file. The server knows no chart's properties.

`name`, `description` and `icon` are platform-reserved names, so the client maps them to
the identity fields without any chart knowledge. Every other key of the file is a chart
value, sent over the stored values. Deploy adds the build's image to the values and
leaves it out of `managed_fields`. The server's existing validation refuses runtime and
undeclared keys, so a typo such as `auht` is refused without new routing logic.

Reserved top-level names are enforced where templates are created
(`templates.create_template`), so admin-created templates and the catalog are covered
alike. `catalog lint` runs the same check without a database. Every catalog schema
passes. Their top-level properties are `host`, `hostname`, `admin`, `auth`, `image`,
`siteName`, `serverName`, `mattermost`, `signups`, `federation` and
`*_PASSWORD`/`*_TOKEN` keys. Templates that exist only in a database, such as the SSO
sandboxes, are checked on dev and prod before rollout. The check applies only on
create, so an existing violation would not fail the migration, but it would make that
product's key unusable in a project file.

### D6. The icon is sent as base64 with every write that carries it

The client sends the icon file's bytes, base64-encoded, on every apply and deploy. Icons
are capped at 256 KiB, so a request carries at most about 350 KB, and typically
15–70 KB. The server hashes the bytes against `icon_source_sha256`. When they match it
does nothing more. Otherwise it runs the product icon pipeline in `services/products.py`:
Pillow decodes the upload and re-encodes it to a PNG of at most 256×256, stored
content-addressed under the static path. SVG is refused because the file is
tenant-controlled content served from the platform's origin. A null icon clears it, and
an absent one keeps it, which is how the dashboard saves without re-sending it.

Reads report `icon_url` only. As a result, `freepod apply` cannot tell whether the icon
changed, so its diff and the unapplied-changes warning leave the icon out.

*Alternative:* send a hash and attach the bytes only when it differs. That needs the hash
in reads, a read before every write, and an `icon_data_required` refusal for a race, all
to save a few kilobytes.

### D7. Init does create + link. `--recreate` folds into `init --force`.

Init now runs the preflight that deploy ran (terms, handle, free plan), prompts for the
name (default: the directory name, unchanged) and then the hostname (default:
`slug(name)`, with `-2`… while unusable, up to five checks). It creates the deployment
through the create deploy uses today. An unlinked file's keys travel in that create with
their `managed_fields`. Init writes only `$schema`, `version`, `deployment` and, when
non-default, `env`. It then exits, saying that provisioning continues in the background.
Nothing it hands over needs the reconcile: the id and the hostname claim come from the
create transaction, vars are accepted while provisioning, and deploy's
`wait_until_settled` covers a first build that finishes early.

*Alternative:* init follows the first reconcile with a spinner. That costs minutes on
every init to show a placeholder page.

Re-pointing a project is always `init --force`, or `init` in an unlinked project, or
`link`. When link creates the file, it writes the deployment's managed fields back into
it. Otherwise the next apply would send an empty `managed_fields` and silently give up
ownership of every field the lost file held. Link's picker uses `prompt_toolkit`, the
client's first dependency for terminal input beyond `click`. Deploy never creates a deployment, so its "create on first deploy", free-plan
selection and `--recreate` paths are deleted rather than kept beside init's. Hostname
suggestion stays in the client. Doing it on the server is a small addition if the
dashboard or GitHub flow ever wants it.

`--name`/`--hostname` flags give agents a prompt-free init. Piping answers on stdin keeps
working, now two lines.

### D8. Format 2 migration happens on read, in the client

The client already rewrites legacy hostnames on load. Migrating format 1 extends that:

- The pointer's id is kept and its name dropped.
- `user_values` keys are lifted to the top level, except `image` and `hostname`.
- `hostname` is dropped when it equals the deployment's, and kept as an owned key
  otherwise. Then an edit made to the file but never deployed is not lost.
- A null pointer becomes an unlinked file.

Format 1 files have no notion of ownership. Their next apply claims exactly the lifted
keys, which matches format 1 behavior, where the file's values always won.

### D9. `$schema` is generated per product by the API

`GET /api/products/{slug}/project-schema` builds the file's schema from the canonical
template: the file keys, the metadata keys (with `icon` as a string path, which is its
form in the file), and the chart-routed top-level properties. It is public because
editors fetch it anonymously, and the product listing is public already. Its URL is
per environment, so dev projects validate against dev's template. It describes Custom's
`image` like any other property, and the client refuses `image` in the file.

## Risks / Trade-offs

- **Abandoned inits pile up** as placeholder deployments with a pod, a database and a
  bucket. There is no per-account deployment cap today. → An init is as costly as a
  first deploy that never got a build is today, and it is billed on the owner's plan. It
  appears on the dashboard with Remove. A cap or a sweep can come later.
- **Custom-domain hostnames are claimed at init.** → The CNAME check still runs at
  create, exactly as it does on a first deploy today, so nothing new can be squatted.
- **An unchanged update no longer re-renders a `ready` deployment.** Anyone re-sending
  an update to force a Helm run gets a no-op. → A deployment in `error` still always
  releases, which covers retrying a failure. A forced re-render of a healthy deployment
  is not a supported operation.
- **`name` means different things in SQL and in the API.** The column holds the release
  name and the API's `name` is `display_name`. → Only the daemons and hand-written
  queries see the columns. The ORM attribute is `display_name` too, so Python code
  reads the same as the SQL.
- **Last writer wins on chart values.** The CLI sends the stored values with the file's
  keys over them, so a dashboard edit between its read and its write is overwritten.
  → This is today's deploy behavior, and the managed-field check refuses dashboard edits
  to the file's own keys.
- **app-auth needs new column grants** (`display_name`, `rel_icon_path`). → The grants
  ship in the tf bootstrap before the app-auth image that uses them. Until then the old
  query keeps working.
- **Take-over followed by a stale file.** A teammate's next apply restores the file's
  value. → This is intended, and apply prints the change. The take-over confirmation says
  so.
- **The meaning of the API `name` changes for old clients.** → Old clients only echo it
  into their file. Once the format 2 client ships, the version gate is raised so that old
  clients stop creating deployments named after the product.

## Migration Plan

1. **Server** (PR 1): the migration with its backfill, identity and `managed_fields` on
   create and update, the release rule, reserved keys, the schema endpoint, app-auth
   branding with its grants, the dashboard, and operator CLI parity. It is safe alone:
   no client sends `managed_fields` until PR 2, and the dashboard's writes behave as
   before apart from skipping needless releases.
2. **Client** (PR 2): format 2, init/link/apply/deploy/delete, the skill and the docs.
   Release `freepod`, then raise the client version gate.

Rollback: PR 1's downgrade drops the new columns, so names chosen since are lost, which
is acceptable for a rollback. A format 2 file is refused by older clients with their
existing "upgrade freepod" message, so nothing silently misreads it.

## Open Questions

- Whether the dashboard should show the product's name as secondary text on catalog
  rows (for example `Family photos` with Nextcloud beneath). This is visual polish within
  the apps-dashboard requirement, and can be settled in the UI PR.
