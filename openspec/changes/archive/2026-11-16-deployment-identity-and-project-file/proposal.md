# Proposal

## Why

The deployment model grew organically and now works against developers. The hostname
is stored twice, in `.freepod.json` and on the deployment row, because `freepod init`
deliberately created nothing on the server. The deployment's `name` is a generated Helm
release name that nobody chose and nobody reads. Every Custom deployment therefore shows
on the dashboard as the same "Custom user app" with the same icon. Vars cannot be set
before the first deploy, because the deployment does not exist yet. And the project file
exposes `user_values`, a Helm-side concept, to the developer.

## What Changes

- **`freepod init` creates the deployment** on the server, through the same create a
  first deploy uses today, so the hostname is claimed and vars can be set before the
  first build. The deployment serves Custom's placeholder until then. Init returns as
  soon as the creation is accepted and leaves provisioning to run in the background. The
  first deploy waits for it if it is still running.
- **Deployments get an identity of their own.** Every deployment, whatever its product,
  gets a free-form `name` that the owner chooses, that is unique among their live
  deployments, and that can be renamed. It also gets an optional `description` and icon,
  which override the product's when set. Custom remains an ordinary catalog product. The
  dashboard and the Sign in with Freepod page show the deployment's identity. The
  hostname stays independent of the name. Init only suggests a hostname derived from it.
- The generated Helm release name keeps its `name` column and stops appearing in API
  reads. The owner's name lives in a new `display_name` column, which reads report as
  `name`.
- **Project file format 2.** The layout is flat, with no `user_values` element. The
  deployment pointer is an id, present or absent but never null. A `$schema` URL
  generated per product gives editors autocompletion. Init writes only the pointer and
  the environment. **BREAKING:** clients migrate format 1 files on read.
- **Presence of a key is ownership.** A key in the project file is owned by the file.
  The CLI sends the list of owned keys as `managed_fields`, and the server records it.
  The server refuses changes to those fields from any request that carries no list
  (`409 managed_by_project_file`). The dashboard shows them read-only, and offers a
  take-over that gives a field back to the dashboard.
- **One write endpoint.** The existing `PUT /api/users/{uid}/deployments/{id}` also
  carries the name, description, icon and managed fields, and create accepts the same
  fields. An update cuts a release only when the running app would change. A rename is
  an instant row update with no reconcile. The server keeps no knowledge of any one
  chart's properties.
- **Icons travel as base64** in the create or update, capped at 256 KiB, and the server
  skips re-encoding an icon it already has.
- **New `freepod apply`.** It pushes the project file without building and prints what
  changed. `freepod deploy` applies the file in the same release as the new image.
  `deploy --no-build` becomes an alias of `apply`. New `freepod link` points a project at
  an existing deployment, by name or id or from an interactive list, and recreates a lost
  file's managed fields. **BREAKING:** `deploy --recreate` is replaced by
  `init --force`.
- Template validation reserves the metadata and file keys as top-level property names.

## Capabilities

### New Capabilities

- `deployment-identity`: a deployment's own name, description and icon. Covers their
  product fallback, uniqueness and defaults, how create and update write them, and the
  surfaces that display them.
- `deployment-project-file`: the platform's side of the project file: its reserved keys,
  managed fields and their enforcement and take-over, and the generated JSON Schema.
- `cli-apply`: `freepod apply`, which pushes the project file to its deployment.
- `cli-link`: `freepod link`, which points a project at an existing deployment.

### Modified Capabilities

- `deployment-naming`: the generated release name keeps its column and is no longer
  reported by reads.
- `edit-deployment-backend`: the update carries identity, releases only when the running
  app would change, and requires a settled status only when it releases.
- `deployment-release-ledger`: an update that changes nothing the app runs creates no
  release.
- `deployment-create-contract`: create accepts a name, description, icon and managed
  fields, and refuses a name already in use. Reads report the owner's name as `name`.
- `cli-init`: init creates the deployment, prompts for a name and a suggested hostname,
  and writes only the pointer.
- `cli-project-file`: format 2, a flat layout, the pointer, and migration from format 1.
- `cli-deploy`: deploy applies the project file in the release. `--recreate` is removed,
  and the hostname rules move to the platform.
- `cli-delete`: after a deletion the file is unlinked, not left with a null pointer.
- `apps-dashboard`: rows show the deployment's name and icon.
- `edit-deployment-frontend`: edit name, description and icon. Managed fields are
  read-only, with a take-over.

## Impact

- **API:** one migration (`display_name`, `description`, `rel_icon_path`,
  `icon_source_sha256`, `managed_fields`), the create and update services and their
  release rule, the generated schema endpoint, template validation, and operator CLI
  parity.
- **Daemons:** `app-auth` branding reads the deployment's identity, which needs column
  grants in `tf/app/caelus/app-auth-bootstrap.sql`. `ssh-auth` is unchanged.
- **`freepod` CLI:** `init`, `deploy`, `delete`, the project file, and the new `apply` and
  `link` commands, and a new `prompt_toolkit` dependency for the picker. The client
  version gate is raised for format 2.
- **UI:** dashboard rows, the edit dialog, the identity editor and managed-field
  rendering.
- **Docs:** the developer guides, the generated CLI reference, the `deploy-to-freepod`
  skill (`cli/src/freepod/assets/SKILL.md`), and AGENTS.md's build paragraph.
