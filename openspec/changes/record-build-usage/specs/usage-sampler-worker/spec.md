## MODIFIED Requirements

### Requirement: Progress is derived from the ledger

The sampler SHALL determine where to resume from the ledger itself rather than from
separately held state, so that a crash, restart or redeployment cannot desynchronize
its position from what has been recorded.

It SHALL consider only the samples of the subjects it records itself. Other writers
record into the same ledger, for windows the sampler may not have reached; counting
their samples would move the sampler past windows it never recorded, and skip them
permanently.

#### Scenario: A crashed run resumes correctly

- **WHEN** the sampler is terminated mid-run and restarted
- **THEN** it resumes from the last window present in the ledger, with no gap and no
  duplicate

#### Scenario: Another writer's samples do not advance the sampler

- **WHEN** a build's usage is recorded for a window the sampler has not yet recorded,
  for example while its measurement source is unavailable
- **THEN** the sampler still records that window once it can

## ADDED Requirements

### Requirement: Builds are not sampled where they are recorded directly

The sampler SHALL NOT record workloads in its own environment's builds namespace. Those
builds' usage is recorded directly from their own measurements, and sampling them as well
would record the same consumption twice.

Another environment's builds namespace SHALL be treated as any other platform namespace.

#### Scenario: Own builds are skipped

- **WHEN** the sampler observes a workload in its own environment's builds namespace
- **THEN** it is not recorded

#### Scenario: Another environment's builds are platform overhead

- **WHEN** the sampler observes a workload in another environment's builds namespace
- **THEN** it is recorded with no deployment attributed, like any other platform workload
