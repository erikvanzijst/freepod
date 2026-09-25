## Context

See proposal.md for why. Two recorded decisions are reversed here, and their reasoning
is answered below rather than ignored:

- `add-build-subsystem` D1 kept builds free of any deployment reference because "most
  products never build anything, and a single deployment may need several images".
- `add-freepod-cli` D6 built before creating the deployment, to avoid a 409 on updating a
  deployment that is still provisioning, and to avoid a first deploy rolling out the
  placeholder before the real image.

The `custom` chart already falls back to `placeholderImage` when `image` is empty, so a
deployment created with no image is a supported state today.

Measured on 2026-09-25, before writing this:

| | builds | linked by release `build_id` | linked only by release image | unlinkable |
|---|---|---|---|---|
| dev | 51 | 22 | 11 | 18 (15 succeeded) |
| prod | 78 | 56 | 6 | 16 (9 succeeded) |

Two dev builds had their image released into two deployments each. All four deployments
involved are deleted CLI test deployments from August 2026.

## Goals / Non-Goals

**Goals:**

- A build cannot exist without a deployment, enforced by the schema.
- One source of truth for a build's owner.
- A first deploy that works with the build anchored to a deployment, with `init`
  unchanged.

**Non-Goals:**

- Automatically releasing a successful build. The client still composes build and
  release.
- Limiting builds to products whose chart consumes an image (see D4).
- Removing the orphaned registry images of deleted builds.
- A compatibility path for clients built against the account-level build routes.

## Decisions

### D1: `build.deployment_id NOT NULL`, and `build.user_id` is dropped

The foreign key has no cascade. Deployments are soft-deleted, so the referenced row
survives a deletion and a deleted deployment's builds remain readable — build history is
provenance for releases that still exist.

`user_id` is dropped rather than kept alongside. The owner is needed in three places —
the artifact key prefix, the registry repository `{user_id}@digest`, and the push
capability's scope — and all three read it through the deployment. The worker already
loads the build; it joins the deployment.

*Answering add-build-subsystem D1:* a foreign key from build to deployment asks nothing
of deployments, so products that never build are unaffected, and many builds per
deployment accommodates a deployment consuming several images. The one cardinality it
cannot express is one build made for several deployments, which the data shows has never
been a real use: the only cases are test deployments. Reusing an image elsewhere remains
possible (D5).

*Alternative considered:* keep `user_id`, pinned to the deployment's owner by a
composite foreign key `(deployment_id, user_id) → deployment(id, user_id)`. Rejected:
it saves a join on a table that is small and rarely read in bulk, and costs a second
unique constraint on `deployment` purely to prop it up.

### D2: Backfill by provenance, then by image, then delete

The migration links each existing build in three steps, stopping at the first that
answers:

1. a release that recorded the build's id (`deployment_release.build_id`);
2. otherwise a release whose `values_json->>'image'` equals the build's `image` — these
   are releases made by `freepod deploy --no-build` or by the API without naming a
   build;
3. where either step matches several deployments, the one whose matching release was
   created first.

Builds that match no release are deleted, their logs with them. No release refers to
any of them, so nothing running is affected. Their images stay in the registry under
their build-id tags, referenced by nothing; registry cleanup is a separate concern this
change does not make worse.

The migration refuses to run while any build is `queued` or `running`, because such a
build cannot be linked yet and deleting it would pull the row out from under the worker.
It fails with a message saying to retry once builds settle, rather than waiting.

*Alternative considered:* leave the column nullable for historical rows. Rejected: a
nullable column is an invitation for new code to write a null, and the rows it would
preserve have no deployment to show them under.

### D3: Builds nest under the deployment; the old routes are removed outright

Every build endpoint moves to `/users/{user_id}/deployments/{deployment_id}/builds`.
The deployment is resolved under the owner in the path, as every deployment
sub-resource already is; the existing self-or-administrator guard applies unchanged. A
build requested under a deployment other than its own is not found.

The account-level routes are deleted with no alias and no `410` shim. The installed
clients are ours; a missing route fails loudly at the build step, and the fix is the
upgrade either way.

### D4: No gating on product or chart values

A build is refused only for a deployment that is `deleting` or `deleted`, since nothing
can be released into it.

*Alternative considered:* refusing a build for a deployment whose product schema has no
`image` property. Rejected for the reason `deployment-release-ledger` already records:
`image` is a value of one chart, not a platform concept, and the build path should not
learn any product's schema. A build against a deployment whose chart ignores images
wastes a build and harms nothing.

### D5: A release's named build must belong to that deployment

Update requests naming a build are checked against the deployment being updated, not
merely its owner. A creation request naming a build is refused, since no build can belong
to a deployment that does not exist yet — and the new CLI never sends one.

An image can still be released into a deployment other than the one it was built for,
by submitting it without naming a build. The chart's owner assertion (`add-build-subsystem`
D14) is what guards image use, and it is unchanged.

### D6: `deploy` creates the deployment; `init` still writes nothing

The ordering becomes preflight → **create (if none) → record pointer** → pack → upload →
build → wait for ready → release. The deployment is created with no `image` and no
build, so the placeholder serves until the first release.

*Answering add-freepod-cli D6:*

- The 409 on updating a still-provisioning deployment is already handled: the client
  waits for `ready` or `error` before every update. A build takes a median of 65 s, so
  the deployment is almost always ready by the time the build is.
- The placeholder rollout before the real one is accepted. It is an appropriate landing
  page, and creating first starts the hostname's TLS provisioning while the build runs.

`init` stays read-only (`add-freepod-cli` D5): a command called `init` should not
provision a resource, and `git clone && freepod deploy` must keep working in a checkout
with no deployment pointer, which it does because `deploy` creates it.

The pointer is written to `.freepod.json` straight after creation, before packing. A
failed pack, upload or build then leaves a deployment the next `deploy` reuses, rather
than an orphan the user cannot see. The client says so, and names `freepod delete`.

*Alternative considered:* having `init` create the deployment, which would also reserve
the hostname earlier. Rejected: username wildcard subdomains have made hostname races
rare, and a resource created by `init` is surprising.

### D7: The build history is the project's, with no account-wide option

`freepod builds` reads the project file and lists that deployment's builds. Outside a
project, or before a first deploy, it refuses and says why. No `--all` is added: the
account-wide view existed only because nothing narrower did.

### D8: An artifact's in-flight build is only returned to its own deployment

Creation stays idempotent per artifact (`uq_open_build_per_artifact` is unchanged). The
existing build is returned only when it belongs to the deployment in the path; if it
belongs to another, creation is refused with 409. Artifacts are per upload, so this only
arises from a client deliberately submitting one upload for two deployments.

## Risks / Trade-offs

- **Installed CLIs break at the build step.** → Accepted (D3). The server change and the
  CLI release ship together; the release notes say to upgrade.
- **A failed first build leaves a live placeholder deployment.** Previously it left
  nothing. → The client says so and names `freepod delete`; the next deploy reuses it.
- **The migration deletes rows.** 18 builds on dev and 16 on prod, with their logs. →
  None is referenced by any release. The downgrade restores the schema, re-deriving
  `user_id` from the deployment, but cannot restore the deleted rows.
- **A build in flight blocks the migration.** → It refuses rather than guessing; with
  builds taking about a minute, a retry succeeds.

## Migration Plan

1. Merge the server change and the CLI change together.
2. The migration runs from the API and worker init containers on rollout, dev first. It
   refuses while a build is in flight; the init container retries on its own.
3. Publish the CLI release to PyPI once dev is verified, then roll out to prod.
4. Verify on each environment: every build has a deployment, `freepod builds` in a
   project lists only that project's builds, and a first deploy of a new directory shows
   the placeholder, then the built app.

**Rollback:** the downgrade re-adds `build.user_id`, fills it from each build's
deployment, and drops `deployment_id`. Deleted builds are not restored. The previous CLI
release works again once the old routes are back.
