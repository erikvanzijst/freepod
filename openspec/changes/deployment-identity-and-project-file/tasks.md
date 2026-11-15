# Tasks

Groups 1–5 are PR 1 (server) and groups 6–8 are PR 2 (client), per design.md's Migration
Plan. Run the full `api/` suite before every push.

## 1. Identity data (PR 1)

- [x] 1.1 Check every template on dev and prod for top-level properties using reserved keys, via `caelus` in the API pod; record the result in the PR (expected: none)
- [x] 1.2 Migration adding `display_name`, backfilled per deployment-identity (label of a `custom` tenant hostname, whole custom domain, else product name, then ` 2`… per owner) and made NOT NULL, with the partial unique index on `(user_id, lower(display_name))`, plus `description`, `rel_icon_path`, `icon_source_sha256` and `managed_fields`; the ORM attribute is `display_name`, and `name` keeps the release name; verify with a migration test over fixtures covering each backfill rule and a collision, and its downgrade
- [x] 1.3 Identity validation: name rules (trim, 1–100, no control characters), the create default with numeric suffix, `name_in_use` mapped from the index violation, description ≤ 500; verify with service tests for each scenario in deployment-identity
- [x] 1.4 Icon handling on the product icon pipeline: base64 PNG/JPEG/WebP ≤ 256 KiB, SVG refused, re-encoded ≤ 256×256 PNG, source SHA-256 recorded, an equal hash skipped without decoding, null clearing it; verify with tests for each format, an oversized icon and a repeated one
- [x] 1.5 Reads report `name` from `display_name`, `description`, `icon_url` and `managed_fields`, and no release name; verify with API tests, and with `grep` that no UI or `freepod` code reads a deployment's `name` as a release name

## 2. One write endpoint (PR 1)

- [x] 2.1 Create accepts `name`, `description`, `icon` and `managed_fields`, with the name checked before any subscription or checkout; verify with API tests for each scenario in deployment-create-contract
- [x] 2.2 Update accepts `name`, `description` and `icon`, and `desired_template_id` becomes optional, defaulting to the current one; verify with API tests for an identity-only update
- [x] 2.3 The release rule: release only for changed chart values, another template, a named build, vars carried (not staged vars alone), or a deployment in `error`; otherwise a row update with no release, no reconcile and no status guard. Existing tests that assumed every update releases are revised to the new rule; verify with tests for every scenario in edit-deployment-backend and deployment-release-ledger
- [x] 2.4 `managed_fields`: set when carried, each key an identity key or a top-level chart property, and `409 managed_by_project_file` for a request without the list that changes a managed value; take-over is the list minus one key; verify with tests for each scenario in deployment-project-file, as owner, admin and operator CLI
- [x] 2.5 Reserved top-level property names refused in `templates.create_template` and in `catalog lint`; verify with tests for a top-level `name` (refused) and a nested `admin.name` (accepted), and that `caelus catalog lint` passes on the current catalog
- [x] 2.6 `GET /api/products/{slug}/project-schema`: public, generated from the canonical template; verify with a test that validates a sample format 2 file against the Custom schema with `jsonschema`, and that an undeclared key is refused
- [x] 2.7 Operator CLI parity: `caelus create-deployment` and `update-deployment` accept `--name`, `--description`, `--icon`/`--clear-icon` and `--managed-fields`; verify with CLI tests
- [x] 2.8 Add identity and managed fields to AGENTS.md's architecture notes as a terse entry with spec links, and update the build paragraph ("a first `freepod deploy` creates the deployment") to name init; verify the links resolve

## 3. Sign-in branding (PR 1)

- [x] 3.1 Grant `caelus_app_auth` `SELECT (display_name, description, rel_icon_path)` on `deployment` in `tf/app/caelus/app-auth-bootstrap.sql`; verify with `terraform plan` on dev that only the grant changes
- [x] 3.2 `app-auth` brands from the deployment's name and effective icon (`coalesce` with the product's); verify with `go test ./...` in `daemons/app-auth` covering a deployment with and without its own icon, and bump the daemons version

## 4. Dashboard identity (PR 1)

- [x] 4.1 Rows show the deployment's name and effective icon. Search covers the name and sort by name uses it; verify with Vitest cases for two Custom deployments, one with its own icon
- [x] 4.2 An identity section in the Settings dialog (name, description, icon upload/reset) as an extracted component, saved in the same update as the chart values, leaving out an unchanged icon, with `name_in_use` on the field; verify with Vitest cases for rename, icon reset and the conflict
- [x] 4.3 Managed fields read-only and marked "managed by `.freepod.json`", updates re-sending managed values unchanged and carrying no `managed_fields`, and Take over behind a confirmation sending the list minus the key; verify with Vitest cases for managed `auth` and a name take-over
- [x] 4.4 Update `ui/docs` app and developer pages that show the dashboard row or Settings; verify the docs build

## 5. Server rollout (PR 1)

- [ ] 5.1 Roll out the API, the grants and app-auth on dev, then prod; confirm on dev that a rename from the dashboard creates no release and that a sign-in page shows the deployment's name
  - Dev done 2026-11-15 (API/UI 191453c pinned, daemons 0.11.0); prod after merge

## 6. Client: project file format 2 (PR 2)

- [x] 6.1 Format 2 model in `cli/src/freepod/project.py`: flat keys, a string or absent pointer (null refused), `$schema` per environment, `image` refused as a build output, and accessors for the identity keys, the chart keys and the managed list; verify with `test_project.py` cases
- [x] 6.2 Format 1 migration on read (pointer id kept, `user_values` lifted except `image`, `hostname` dropped when equal to the deployment's, a null pointer becoming unlinked), with a message; verify with tests for each scenario in cli-project-file
- [x] 6.3 `freepod delete` removes the `deployment` key and keeps the rest; verify with `test_delete.py`

## 7. Client: init, link, apply, deploy (PR 2)

- [ ] 7.1 `freepod init`: name prompt (directory name default, `--name`) checked against the caller's live deployments, offering ` 2`… for a taken directory name and failing early on a taken file `name`, hostname prompt (slug of the name, `-2`… up to five checks, `--hostname`), other required values, the preflight moved from deploy (terms, handle, free plan), creation through the existing create path, then writing the pointer and exiting without waiting for the reconcile, with a message that provisioning continues, re-prompting on `name_in_use` and hostname conflicts, and the `freepod link` hint when writing fails; verify with `test_cli.py` cases for each cli-init scenario, including a non-interactive run
- [ ] 7.2 `init` on an unlinked file sends the file's keys and `managed_fields` in the create, and `init --force` re-points while naming the unlinked deployment; verify with tests
- [ ] 7.3 `freepod link <name-or-id>` with `--force`: a new file recreating the deployment's managed fields except `icon`, an existing file kept and its differences reported, including managed fields it lacks; verify with tests for name and id matches, no match, an already-linked file, a recovered file followed by a no-op apply, and a managed icon
- [ ] 7.4 `freepod link` without an argument: a picker built on `prompt_toolkit`, added as a dependency of the client, listing name, hostname and product with arrow keys and type-to-filter, failing without a terminal and naming `freepod init` when there are no deployments; verify with tests driving the picker through `prompt_toolkit`'s pipe input, and by hand in a terminal
- [ ] 7.5 `freepod apply`: one update with the identity keys, the stored chart values with the file's keys over them, and the file's keys as `managed_fields`; the icon as base64, failing before sending when missing or over 256 KiB; a diff against the read taken before the update, without the icon; a rollout followed when a release was created; staged vars rolled out by naming the running release's build, or a note that they wait for the next deploy when it names none; and `deploy --no-build` as an alias; verify with tests for each cli-apply scenario
- [ ] 7.6 `freepod deploy` sends the same update plus `build_id`, `desired_template_id` and the build's image as `image`, which stays out of `managed_fields`, keeps `wait_until_settled` before it, and loses the create path, plan selection, `--recreate` and the hostname re-check; verify with `test_deploy.py`, including a first deploy that waits out a deployment still provisioning, and an unlinked project naming init
- [ ] 7.7 The unapplied-changes warning on other project commands, leaving out the icon; verify with a test on `freepod log`

## 8. Client docs and rollout (PR 2)

- [ ] 8.1 Update `cli/src/freepod/assets/SKILL.md` (init with `--name`/`--hostname`, editing the file plus `freepod apply`, `link`, no `--recreate`), `cli/README.md` and `cli/DEVELOPMENT.md`; verify the skill's command examples run against dev
- [ ] 8.2 Update the developer guides in `ui/docs`, describe fields "managed by `.freepod.json`" and Take over on `apps/managing/settings.md` (left out of PR 1, when no client sets them yet), and run `npm run cli:reference`; verify CI's stale-reference check passes locally
- [ ] 8.3 End-to-end on dev: `init` (returns before provisioning ends, the placeholder comes up, vars settable), `deploy` (app online, one release), rename and icon in the file plus `apply` (no release), a dashboard take-over and re-apply, a format 1 project migrated; record the results in the PR
- [ ] 8.4 After the `freepod` release, raise the server's minimum client version; verify an older client is told to upgrade before it reads a format 2 file

## Workflow follow-up

- Update the Purpose of `openspec/specs/deployment-naming/spec.md` after archiving, so it says reads report the owner's name and the release name stays internal.
- Archive the change and sync its delta specs once both PRs are merged and live on dev and prod.
- At archive, repoint AGENTS.md's identity entry from the change's delta specs and design to `openspec/specs/` and the archive path.
