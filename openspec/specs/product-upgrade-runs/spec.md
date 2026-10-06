## Purpose

What a run of the upgrade service is: when one starts, which products it covers, how
each product is executed and bounded, why only one runs at a time, and what becomes of a
run that a restart cuts short.

## Requirements

### Requirement: The catalog runs nightly
The service MUST start a run over the whole catalog once a day, at the local time
`SCHEDULE_TIME` in the zone `SCHEDULE_TIMEZONE`. It MUST NOT start one when
`SCHEDULE_TIME` is `off`.

If the scheduled time passes while another run is active, the scheduled run MUST start as
soon as that run finishes. If it passes while the service is not running, it MUST NOT be
made up later.

A local time that does not exist on a given day, because the clocks go forward, MUST
trigger at the first valid instant after it. A local time that occurs twice, because the
clocks go back, MUST trigger once.

#### Scenario: The nightly run
- **WHEN** the clock in `Europe/Brussels` reaches 03:00 with `SCHEDULE_TIME=03:00` and no run active
- **THEN** a run over the whole catalog starts, recorded as scheduled

#### Scenario: The nightly time arrives during another run
- **WHEN** 03:00 passes while a run started from the dashboard is still active
- **THEN** the nightly run starts when that run finishes

#### Scenario: The service was down at the scheduled time
- **WHEN** the service starts at 03:10, having not run at 03:00
- **THEN** no run starts until the next day's 03:00

#### Scenario: The clocks go forward
- **WHEN** `SCHEDULE_TIME` is `02:30` on the day `Europe/Brussels` moves from 02:00 to 03:00
- **THEN** that day's run starts at 03:00 local time

#### Scenario: The clocks go back
- **WHEN** `SCHEDULE_TIME` is `02:30` on the day `Europe/Brussels` passes 02:30 twice
- **THEN** exactly one run starts that day

#### Scenario: The schedule is off
- **WHEN** `SCHEDULE_TIME` is `off`
- **THEN** no run starts except those requested from the dashboard

### Requirement: Runs can be requested on demand
A request to run the whole catalog, or one named product, MUST start a run at once when no
run is active.

While a run is active, a new request MUST be refused with a message saying why. It MUST
NOT be queued behind the active run.

#### Scenario: Run now
- **WHEN** the owner requests a run of the whole catalog while no run is active
- **THEN** a run over the whole catalog starts at once, recorded as manual

#### Scenario: Run one product
- **WHEN** the owner requests a run of `nextcloud` while no run is active
- **THEN** a run starts that executes `nextcloud` and no other product

#### Scenario: A request during an active run
- **WHEN** the owner requests a run while another run is active
- **THEN** the request is refused, and no run starts because of it

#### Scenario: A request names a product that is not eligible
- **WHEN** a run of one product starts and that product is not among the eligible products on `master`
- **THEN** the run records that product as `failed`, with an error saying it is not eligible

### Requirement: An active run can be canceled
The owner MUST be able to abort the run executing now. The service MUST then end the
running session and every process it started, record that product as `canceled`, and
record the run as `canceled` without starting any of its remaining products.

A session that does not end when it is asked to MUST be killed, so that a cancel always
takes effect. The product's files MUST still be stored, as they are for any other outcome
(`product-upgrade-history`), so that the session that was aborted can still be read.

A cancel MUST apply only to the run it names: one naming a run that is no longer active
MUST change nothing, and MUST NOT affect the run that follows.

#### Scenario: Canceling a doomed session
- **WHEN** the owner cancels a run whose first of three products is running
- **THEN** that session and its child processes are terminated
- **AND** the first product is recorded as `canceled`, with its transcript stored
- **AND** the other two never start, and the run is recorded as `canceled`

#### Scenario: A session that ignores the ask
- **WHEN** the running session does not exit after being asked to end
- **THEN** it is killed, and the run still finishes as `canceled`

#### Scenario: Canceling a run that is no longer active
- **WHEN** a cancel names a run that has already finished
- **THEN** nothing is canceled, and the request reports that the run is no longer active

#### Scenario: The next run is unaffected
- **WHEN** a run is requested after one was canceled
- **THEN** it starts normally and runs every product it covers

### Requirement: At most one run is active
A run MUST count as active from its start until its finish time is recorded. The service
MUST NOT start a run while another run is active, and it MUST NOT execute two products at
the same time.

#### Scenario: A double click
- **WHEN** "Run now" is submitted twice in quick succession while no run is active
- **THEN** exactly one run starts, and the second request is refused

### Requirement: An interrupted run is closed at the next start
When the service starts, it MUST mark `interrupted` every run and every product result
that has no finish time, using the time of that start as their finish time. It MUST NOT
resume or retry them.

#### Scenario: A restart in the middle of a product
- **WHEN** the container restarts while the second of three products is running
- **THEN** after the restart, the run and the second product's result are shown as `interrupted`
- **AND** the third product never runs as part of that run
- **AND** the next run starts normally

### Requirement: A run covers the products with a real upstream
A run over the whole catalog MUST cover exactly the catalog files on `master` at the
run's start that declare an `upstream` block whose source repository is not the
placeholder `OWNER/REPO`. It runs them in slug order.

#### Scenario: The placeholder is excluded
- **WHEN** a run starts on a catalog of `custom` (placeholder upstream), `immich`, `nextcloud` and `vaultwarden`
- **THEN** the run covers `immich`, `nextcloud` and `vaultwarden`, in that order

#### Scenario: A new product is picked up without a release
- **WHEN** a catalog file with a real `upstream` block is merged to `master`
- **THEN** the next run covers that product, and the service is not redeployed

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
- **WHEN** a session exits with a `result.json` whose `schema_version` is `1`
- **THEN** the service resumes the session once with the validation error
- **AND** the product's outcome comes from the corrected `result.json`

#### Scenario: A result for the wrong product
- **WHEN** the session for `immich` writes a `result.json` whose `product` is `nextcloud`
- **THEN** the `immich` product is recorded as `failed`

#### Scenario: A session claims to have opened a pull request
- **WHEN** a session writes a `result.json` with `status` `opened`
- **THEN** the result is rejected as not following the contract, and the session gets its repair turn

### Requirement: Dry run unless told otherwise
The service MUST run in dry-run mode unless `UPGRADE_DRY_RUN` is exactly `0` when a run
starts. Each run MUST record the mode it ran in.

#### Scenario: The default
- **WHEN** a run starts with `UPGRADE_DRY_RUN` unset
- **THEN** the run is recorded as a dry run, and its sessions run with `UPGRADE_DRY_RUN=1`

#### Scenario: A value that is not zero
- **WHEN** a run starts with `UPGRADE_DRY_RUN=false`
- **THEN** the run is a dry run

#### Scenario: Real pull requests
- **WHEN** a run starts with `UPGRADE_DRY_RUN=0`
- **THEN** the run is recorded as a real run, and its sessions run with `UPGRADE_DRY_RUN=0`

### Requirement: A real run's proposal is published by the service
When a real run's session ends with an accepted result whose `status` is `would_open`, the
service MUST publish the proposal itself:

1. Apply the session's `change.patch` to the service's own clone, on top of
   `master` as it is when the service checks the proposal.
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

The title and description MUST be redacted like every stored file before they are sent,
so that no secret the session could see reaches the public pull request.

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
own clone of `master`, made before the session started, never from the session's clone.

#### Scenario: A result file links to a secret
- **WHEN** a session makes `out/<slug>/body.md` a symbolic link to `/proc/<service pid>/environ`
- **THEN** the service treats `body.md` as missing, and stores nothing it read through the link

#### Scenario: A session rewrites the schema
- **WHEN** a session edits `result.schema.json` in its clone to accept any status
- **THEN** the service still judges `result.json` against the unmodified schema
