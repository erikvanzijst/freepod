## Why

Builds consume real CPU and memory on the cluster, but none of it reaches a bill. Build
pods run in the shared builds namespace, which the usage sampler records as unattributed
platform overhead, and they are too short-lived for its 60-second scrape to measure: of
prod's last two builds, one got a single CPU sample and the other none at all. Builds now
belong to a deployment (`builds-belong-to-deployments`), so the one piece that was
missing — an owner to attribute them to — exists.

## What Changes

- The builder measures its own container's cgroup and reports CPU time, working-set
  memory integrated over time, peak memory and its own start and end time in the
  termination message it already writes, on success and on failure.
- The build worker stores those measurements on the build row when it observes the build
  finish, so nothing is held in memory and nothing is lost to a restart.
- Once every hourly window a finished build spans has closed and settled, the build
  worker records its usage into the existing usage ledger, split across those windows,
  and marks the build recorded — in one transaction.
- Build usage is recorded against a new subject kind, `build`, attributed to the build's
  deployment. It therefore appears under that deployment's application, owner and
  product in every existing report, with no change to reporting.
- A build that ran but reported no measurements is recorded at its resource requests for
  its wall-clock time; having no measurements marks it as estimated.
- The usage sampler derives its resume position from the containers it records alone,
  and stops recording its own environment's builds namespace, so the two writers never
  record the same build or confuse each other's progress.

## Capabilities

### New Capabilities

- `build-usage-recording`: how a finished build's measured resource usage becomes usage
  ledger samples — when, in which windows, with which quantities, and what is recorded
  when measurements are missing.

### Modified Capabilities

- `build-execution`: the build reports its resource usage alongside its result.
- `build-data-model`: a build records its measured usage and whether that usage has
  reached the ledger.
- `usage-ledger-data-model`: a subject may be a build.
- `usage-sampler-worker`: progress is derived from the sampler's own subjects, and its
  own environment's builds namespace is not sampled.

## Impact

- **Builder image:** `products/custom/builder/build.py` gains a cgroup reader and a
  background memory sampler; `VERSION` is bumped and the new image rolled out through
  `builder_image`. Builds from the previous image are recorded as estimated.
- **Database:** new columns on `build`; no change to the usage tables.
- **Build worker:** stores measurements when a build finishes, and records usage for
  settled builds on each pass.
- **Usage sampler:** a narrower resume query and one skipped namespace.
- **Not included:** builds that ran before this ships are not backfilled; reports do not
  yet separate build usage from runtime usage; network and storage are not recorded for
  builds.
