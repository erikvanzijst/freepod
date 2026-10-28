## Context

A build pushes its image to `u/{owner}:{build_id}` and reports `{owner}@{digest}`
(`products/custom/builder/build.py`). The tag is bookkeeping only: nothing deploys by
it, and it exists so `registry garbage-collect --delete-untagged`, which runs as the
registry Deployment's init container on every scheduled restart, cannot reclaim an image
a deployment references by digest. Nothing ever removes a tag, so collection only ever
reclaims superseded build cache and never an image. The registry design said so
explicitly (authenticated-tenant-registry D16: "Collection now, retention later").

What deploys an image is a **user value** (`image` in the `custom` chart, pattern
`^[0-9]+@sha256:[a-f0-9]{64}$`), snapshotted onto each release. A release's `build_id`
is provenance only: a release may carry a build's image while naming no build, including
another deployment's build ("An image reused without its build"). Any rule keyed on
`build_id` alone would therefore miss images that are actually running.

Measured against registry `3.1.1` with tokens minted by `registry_tokens.mint`:
`DELETE /v2/{name}/manifests/{tag}` removes that one tag and leaves other tags on the
same digest intact. It requires the `delete` action (`pull` alone, and a build's
`pull`+`push`, are refused with 401). `tags/list` requires `pull`. The catalog stays
refused. After the last tag is removed, collection reclaims the image's layers.

## Goals / Non-Goals

**Goals:**

- Bound each owner's image repository to what a deployment runs, is rolling out to, or
  could roll back to.
- No stored retention state: the ledger already records everything the rule needs.
- No window in which a write is accepted for an image the prune is about to remove, or
  has removed.

**Non-Goals:**

- Pruning the build cache (`cache/{owner}`). It is one moving tag per owner, already
  collected, and its growth is bounded by collection frequency, not by retention.
- Pruning the mirrored Railpack repositories.
- Reporting retention in build listings or the CLI's build history. The write-time
  rejection is what a user meets; a derived field can be added later without changing
  this rule.
- Quotas or billing for registry storage.

## Decisions

### D1: Retain by image value, per owner

The retained set is a set of digests **per owner**, not per deployment: the repository
is per owner, and the same image can be carried by two of an owner's deployments. A digest
D is retained for owner O when the string `O@D` appears, as a value anywhere in the user
values, in a retained release of one of O's live deployments (spec: "Retained images are
derived from the release ledger"). No chart value key becomes a platform concept.

SQL selects only the owner's live releases, through the indexes; the owner's image
references are matched in Python on the decoded values, by the owner's literal prefix.
A jsonpath walk over every leaf costs far more than the documents are worth matching.

Alternative considered: retain by `release.build_id`. Rejected because it misses images
carried without a build, and because one digest can come from several builds. Deciding by
digest makes both cases fall out.

### D2: Desired, applied, and two earlier distinct images

For each live deployment, walk releases by `number` descending:

- the desired release and the applied release are retained unconditionally;
- then collect owner images from earlier releases, skipping any already retained, until
  two distinct ones are found. Each release that contributes one is retained.

Counting **distinct images**, not releases, matters: vars changes and `--no-build`
redeploys create many releases carrying one image, and counting those would leave the
window holding a single real rollback target. The count is a setting
(`registry_retained_past_images`, default 2), so the rule can be widened without
touching the spec's shape. The spec states two; changing the default is a spec change.

### D3: Fresh builds by build row, not by digest

Between the push and the worker recording `succeeded`, the tag exists but the database
has no image for it, so a digest-only rule would see an unretained tag. Fresh builds
are therefore judged by **tag name**: a tag naming one of the owner's builds that is open,
or that succeeded within `registry_prune_grace_hours` (default 24), is kept whatever it
points at. The same grace makes the build's image retained for the write-time check, so
`freepod deploy`'s build-then-update sequence, and a retry of a failed update, both pass.

### D4: Read the registry first, then the database

The prune lists every owner's tags **first**, **then** reads the ledger and builds, **then**
deletes. A tag named after a build is judged by that build's recorded image, since a build
tag never moves; only a tag naming no known image costs a `HEAD` for its digest. Leaving retention is permanent (spec), and
a write that would re-admit an image is rejected. So a database read taken after the
registry read can only see the same or more retained images than were real when the tags
were listed:

- a tag pushed after the listing is not in the listing, so it is not judged;
- a tag listed while its build was still running is kept by D3;
- a release written after the database read can only carry an image that was retained
  at that read, so the image is already in the keep set.

No lock between the prune and writes is needed.

### D5: Delete tags, never manifests by digest

`DELETE …/manifests/{digest}` removes the manifest and every tag on it, so a reproducible
build whose digest a retained build shares would lose its image. Deleting by tag removes
one anchor at a time, and collection reclaims an image only when its last anchor goes.
This is what makes "two tags, one image" safe without any special case.

### D6: A CronJob, ahead of collection

The prune runs as `caelus registry-prune` in a daily CronJob in `tf/app/caelus`, at
03:00 UTC: an hour before the registry's restart-and-collect at 04:00, so one night
untags and collects. It uses the API image and the same Secrets as the build worker (the
database URL and the registry signing key). `concurrencyPolicy: Forbid` and a deadline
keep runs from overlapping.

Alternatives considered:

- **Inside the build worker's pass.** It holds the signing key already, but a pass must
  never block (build-worker spec), and the prune makes a few HTTP calls per tag. A second
  loop in that process would share its failure domain for no gain.
- **Inside `caelus db-worker`**, as D16 of the registry design suggested. That process
  owns tenant database housekeeping and does not hold the registry signing key. Giving
  it the key widens the key's exposure to a long-running pod that has no other use for it.

A CronJob holds the key only for the minutes it runs, gives the prune its own logs and
exit status, and makes its order against collection explicit in Terraform.

### D7: The prune's capability

`registry_tokens.prune_token(settings, owners)` mints `pull`+`delete` on `u/{owner}`
for exactly the owners named, validated against the same exact-name grammar as
`operator_token`, with a TTL of at most an hour. The prune mints one per owner. Owners come from the database: every user
who owns a build. The prune never uses the catalog, which stays refused for every
principal.

### D8: The write-time check reuses the rule

`deployments.py` gains one check beside `_validate_build_reference`. It computes the
owner's retained digests as of the transaction's start, then rejects the write when:

- the named build has an image outside that set (code `image_not_retained`, distinct from
  "Unknown build", so clients can say "rebuild"); or
- the submitted user values carry any `{owner}@sha256:…` string outside that set.

The values check matches only the owner's own prefix. Another owner's image cannot be
pulled with this deployment's credential anyway, and judging it would reveal what
another owner retains.

Computing the owner's set runs D1's query over that owner's live deployments only, so it
scales with one owner's release history, not the platform's: a few hundred releases,
well under a second. The rule lives in
one module (`app/services/image_retention.py`) used by both the prune and the check, so
the two cannot drift.

### D9: Dry run first

`caelus registry-prune --dry-run` reports, per owner, tags to remove, tags kept and why
(desired / applied / earlier / fresh). The CronJob ships enabled, but the first apply is preceded by a dry run in each
environment (Migration Plan).

## Risks / Trade-offs

- [A client redeploys an old build by id and is now refused] → Documented as
  **BREAKING** in the proposal. The CLI never does this; the error names the remedy.
- [An operator's `helm rollback` targets a revision whose image was pruned] → The
  operator path is outside the ledger. The two earlier images cover a typical rollback;
  anything older needs a rebuild, as it does for users.
- [A bug in the rule untags a running image] → Running pods are unaffected (the node
  already has the image), but a reschedule onto a fresh node, or an eviction, would fail
  to pull. Mitigations: the rule always retains desired and applied first; tests pin
  every scenario in the spec; the dry run is reviewed before the first enabled run.
- [The prune fails partway] → Each tag deletion is independent and idempotent; the next
  run continues. A failure is visible as a failed Job.
- [Registry downtime during the prune] → Deletions fail and the run exits non-zero;
  nothing is lost.
- [Deleted accounts] → Their deployments are deleted, so they retain nothing and their
  repositories empty out. This is intended.

## Migration Plan

1. Ship the rule, the check and the command; deploy the API (the write-time check takes
   effect immediately and only rejects images that are already outside retention).
2. In each environment, run `caelus registry-prune --dry-run` in the API pod and review
   the report: every applied and desired image must appear as kept.
3. Apply `tf/app` to add the CronJob. The first night untags the backlog and the 04:00
   restart reclaims it.

Rollback: remove the CronJob (no further tags are removed) and revert the API. Tags
already removed are not restored; affected builds must be rebuilt.

## Open Questions

- Whether the prune should also export a metric (tags removed) for the
  registry dashboard, or whether the Job log is enough for now.
