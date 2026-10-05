## ADDED Requirements

### Requirement: A real run's proposal is published by the service
When a real run's session ends with an accepted result whose `status` is `would_open`, the
service MUST publish the proposal itself:

1. Apply the session's `change.patch` to the service's own clone, on top of the
   commit the session started from.
2. Push the result as `upgrade/<slug>-<target_version>`, without force.
3. Create the `product-upgrade` label if it is missing.
4. Open a pull request against `master` with that label, the title from `meta.json`,
   `body.md` as its description, and as a draft when `draft` is true.

The product's recorded outcome is then `opened`, with the pull request's URL and branch.

Before publishing, the service MUST check the proposal. It MUST refuse it when:

- `meta.json`, `body.md` or `change.patch` is missing;
- the patch is empty or does not apply;
- the patch touches any path other than `products/catalog/<slug>.yaml` and files under
  `products/<slug>/`;
- the patch creates a symbolic link or a submodule entry;
- `target_version` does not form a valid branch name;
- the title is not one line of the form `<Product>: Upgrade to <target_version>`;
- `body.md` is longer than GitHub accepts;
- `body.md` contains a link to an issue or pull request on GitHub, or an @-mention.

Those checks are part of judging the result. A refusal is handled like any other rejected
result: it gets the one repair turn, and the product is recorded as `failed` if the
corrected proposal is still refused. The refusal's reason is what the repair turn is
given.

If GitHub refuses the push or the pull request, or cannot be reached, the product MUST
be recorded as `failed` with GitHub's reason. A branch that already exists counts as such
a refusal. Nothing is retried.

In a dry run, nothing is published, and the outcome stays `would_open`. The proposal is
still checked, so that a dry run catches what a real run would refuse.

#### Scenario: A real run publishes
- **WHEN** a real run's session for `immich` ends with `would_open`, target `v2.2.0`, `draft` true, and a patch that changes `products/catalog/immich.yaml`
- **THEN** the service pushes `upgrade/immich-v2.2.0` and opens a draft pull request labeled `product-upgrade`
- **AND** the product is recorded as `opened`, with that pull request's URL

#### Scenario: A patch touches another product
- **WHEN** a session for `immich` proposes a patch that also changes `products/catalog/nextcloud.yaml`
- **THEN** nothing is pushed
- **AND** the session gets its repair turn, told that the patch touches a path outside `immich`'s

#### Scenario: A patch touches the workflows
- **WHEN** a session proposes a patch that changes `.github/workflows/ci.yml`
- **THEN** nothing is pushed, and the proposal is refused before contacting GitHub

#### Scenario: A description links an upstream issue
- **WHEN** a session's `body.md` contains `https://github.com/immich-app/immich/issues/123`
- **THEN** nothing is pushed, and the session gets its repair turn

#### Scenario: The branch already exists
- **WHEN** a real run publishes `upgrade/immich-v2.2.0` while that branch exists on GitHub
- **THEN** the product is recorded as `failed`, naming the existing branch

#### Scenario: A dry run checks without publishing
- **WHEN** a dry run's session proposes a patch that touches another product's files
- **THEN** the session gets its repair turn
- **AND** nothing is pushed, whatever the outcome

### Requirement: The service treats a session's files as untrusted
The service MUST read a file that a session could have created or changed only if:

- no component of its path, below the workspace, is a symbolic link;
- the file is a regular file owned by the session's user; and
- it is below a size limit.

Otherwise the service MUST treat the file as missing. This applies to `result.json`,
`body.md`, `change.patch`, `meta.json`, the session transcript, and the live view of the
transcript.

The service MUST judge a result against `products/UPGRADING/result.schema.json` from its
own clone of the commit the session started from, never from the session's clone.

#### Scenario: A result file links to a secret
- **WHEN** a session makes `out/<slug>/body.md` a symbolic link to `/proc/<service pid>/environ`
- **THEN** the service treats `body.md` as missing, and stores nothing it read through the link

#### Scenario: A session rewrites the schema
- **WHEN** a session edits `result.schema.json` in its clone to accept any status
- **THEN** the service still judges `result.json` against the unmodified schema

## MODIFIED Requirements

### Requirement: Each product runs alone, in a fresh session and a fresh clone
The service MUST execute a run's products one after another. For each product it MUST
start a new agent session, as the session user (`product-upgrade-guardrails`), in a new
workspace, holding a new clone of `master` that the session user owns, with:

- `UPGRADE_PRODUCT` set to the product's slug;
- `UPGRADE_DRY_RUN` set to `1` in dry-run mode and `0` otherwise;
- `UPGRADE_OUT_DIR` pointing into that workspace;
- `UPGRADE_RUN_URL` naming the product's place on its run's page, so that the session can
  send a reviewer back to it (`product-upgrade-skill`), and empty when the deployment has
  no public URL configured;
- the skill loaded from `products/UPGRADING/SKILL.md` in that clone.

The service MUST also keep its own clone of the same commit, which the session cannot
write.

The workspace and both clones MUST be deleted when the product finishes, whatever its
outcome, including every file the session user created. A product that fails MUST NOT
stop the run's remaining products.

#### Scenario: Products do not share context
- **WHEN** a run covers `immich` and then `nextcloud`
- **THEN** the `nextcloud` session starts with none of the `immich` session's messages
- **AND** no file from the `immich` workspace exists when the `nextcloud` session starts

#### Scenario: One product fails
- **WHEN** the first product of a run ends as `failed`
- **THEN** the run's next product still runs

#### Scenario: The session is told where its run is published
- **WHEN** a product's session starts while the deployment has a public dashboard URL
- **THEN** `UPGRADE_RUN_URL` names that run's page and the product within it

#### Scenario: A session leaves files it alone can delete
- **WHEN** a session creates a directory with mode `0500` in its workspace
- **THEN** the workspace is still deleted when the product finishes

### Requirement: Each product is bounded by a timeout
If a product's session has not ended after `PRODUCT_TIMEOUT_MINUTES`, the service MUST
terminate every process running as the session user, including any that left the
session's process group. It then records the product as `timed_out` and continues with
the run's next product. A cancel ends the session the same way.

#### Scenario: A session runs too long
- **WHEN** a product's session is still running after `PRODUCT_TIMEOUT_MINUTES`
- **THEN** the session and its child processes are terminated
- **AND** the product is recorded as `timed_out`
- **AND** the next product starts

#### Scenario: A process escapes the session's group
- **WHEN** a session starts a background process with `setsid` and the product then times out or is canceled
- **THEN** that process is terminated too, before the next product starts

### Requirement: A product's outcome comes from its result file
A product's recorded outcome MUST come from the `status` in the `result.json` its session
wrote, as defined by `product-upgrade-skill`. In a real run, `would_open` becomes `opened`
or `failed` when the service publishes it (see "A real run's proposal is published by the
service"). The service MUST record the product as `failed` instead when:

- the session ended without writing `result.json`;
- `result.json` is not valid under that contract;
- its `product` is not the slug the session was started for;
- its `dry_run` disagrees with the mode the service ran the session in; or
- its `status` is `would_open` and the proposal fails the service's checks.

Before recording such a failure for a session that ended on its own, the service MUST
resume that same session once, giving it the reason the result was rejected, and judge
the result again when that turn ends. The repair turn MUST share the product's timeout
and cancellation, and MUST NOT be repeated.

Outcomes the service assigns itself are `opened`, `timed_out`, `canceled` and
`interrupted`.

#### Scenario: No result file
- **WHEN** a session exits without writing `result.json`, and still has none after its repair turn
- **THEN** the product is recorded as `failed`, with an error saying no result was written

#### Scenario: A result the repair turn fixes
- **WHEN** a session exits with a `result.json` whose `branch` is `""` for `up_to_date`
- **THEN** the service resumes the session once with the validation error
- **AND** the product's outcome comes from the corrected `result.json`

#### Scenario: A result for the wrong product
- **WHEN** the session for `immich` writes a `result.json` whose `product` is `nextcloud`
- **THEN** the `immich` product is recorded as `failed`

#### Scenario: A session claims to have opened a pull request
- **WHEN** a session writes a `result.json` with `status` `opened`
- **THEN** the result is rejected as not following the contract, and the session gets its repair turn
