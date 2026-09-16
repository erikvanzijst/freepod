## Purpose

What a run of the upgrade service is: when one starts, which products it covers, how
each product is executed and bounded, why only one runs at a time, and what becomes of a
run that a restart cuts short.

## ADDED Requirements

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
start a new agent session, in a new workspace, holding a new clone of `master`, with:

- `UPGRADE_PRODUCT` set to the product's slug;
- `UPGRADE_DRY_RUN` set to `1` in dry-run mode and `0` otherwise;
- `UPGRADE_OUT_DIR` pointing into that workspace;
- `UPGRADE_RUN_URL` naming the product's place on its run's page, so that the session can
  send a reviewer back to it (`product-upgrade-skill`), and empty when the deployment has
  no public URL configured;
- the skill loaded from `products/UPGRADING/SKILL.md` in that clone.

The workspace MUST be deleted when the product finishes, whatever its outcome. A product
that fails MUST NOT stop the run's remaining products.

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

### Requirement: Each product is bounded by a timeout
If a product's session has not ended after `PRODUCT_TIMEOUT_MINUTES`, the service MUST
terminate the session and every process it started. It then records the product as
`timed_out` and continues with the run's next product.

#### Scenario: A session runs too long
- **WHEN** a product's session is still running after `PRODUCT_TIMEOUT_MINUTES`
- **THEN** the session and its child processes are terminated
- **AND** the product is recorded as `timed_out`
- **AND** the next product starts

### Requirement: A product's outcome comes from its result file
A product's recorded outcome MUST be the `status` in the `result.json` its session wrote,
as defined by `product-upgrade-skill`. The service MUST record the product as `failed`
instead when:

- the session ended without writing `result.json`;
- `result.json` is not valid under that contract;
- its `product` is not the slug the session was started for; or
- its `dry_run` disagrees with the mode the service ran the session in.

Outcomes the service assigns itself are `timed_out`, `canceled` and `interrupted`.

#### Scenario: No result file
- **WHEN** a session exits without writing `result.json`
- **THEN** the product is recorded as `failed`, with an error saying no result was written

#### Scenario: A result for the wrong product
- **WHEN** the session for `immich` writes a `result.json` whose `product` is `nextcloud`
- **THEN** the `immich` product is recorded as `failed`

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
