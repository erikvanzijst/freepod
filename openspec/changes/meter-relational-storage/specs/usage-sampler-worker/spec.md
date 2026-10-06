## MODIFIED Requirements

### Requirement: Progress is derived from the ledger

The sampler SHALL determine where to resume from the ledger itself rather than from
separately held state, so that a crash, restart or redeployment cannot desynchronize
its position from what has been recorded.

The sampler MAY record from more than one measurement source. It SHALL hold a separate
position for each, derived from the samples of the subjects that source records and no
others. Other writers, and the sampler's other sources, record into the same ledger for
windows a source may not have reached; counting their samples would move that source
past windows it never recorded, and skip them permanently.

#### Scenario: A crashed run resumes correctly

- **WHEN** the sampler is terminated mid-run and restarted
- **THEN** each source resumes from the last window present in the ledger for its own
  subjects, with no gap and no duplicate

#### Scenario: Another writer's samples do not advance the sampler

- **WHEN** a build's usage is recorded for a window the sampler has not yet recorded,
  for example while its measurement source is unavailable
- **THEN** the sampler still records that window once it can

#### Scenario: One source's progress does not advance another

- **WHEN** container usage has been recorded through 15:00 but database sizes only
  through 12:00
- **THEN** database sizes resume from 12:00, not from 15:00

### Requirement: Unavailable measurements do not advance progress

This governs the source being unable to answer, not an answer that is unusable for
attribution — which the preceding requirement covers, and which does advance progress.

When a measurement source is unavailable, returns no data, or returns data whose
measured quantities the sampler cannot trust for a window, the sampler MUST NOT record
samples from that source for that window and MUST NOT advance that source's position
past it.

The sampler MUST record nothing rather than record zero for a window it could not
measure.

One source being unavailable MUST NOT stop the sampler recording from its other
sources.

#### Scenario: An unavailable source leaves no trace

- **WHEN** the measurement source cannot be reached
- **THEN** no samples are written from it, its resume position is unchanged, and the
  window is recorded on a later run

#### Scenario: Other sources keep recording

- **WHEN** the database size measurements are unavailable while container usage is
  available
- **THEN** container usage continues to be recorded, and database sizes catch up once
  their measurements return

### Requirement: Attribution comes from the platform's own records

The sampler SHALL resolve a workload's owning deployment from the platform database,
using the namespace the workload was observed in. It MUST NOT treat metadata supplied by
the measurement source as authoritative for attribution.

A workload whose namespace does not resolve MUST still be recorded, with attribution
left unresolved and able to be completed later.

Subjects that are not workloads, such as tenant databases, SHALL be attributed from the
platform's own record of that subject instead.

#### Scenario: Attribution survives the namespace disappearing

- **WHEN** usage for a past period is attributed after the namespace has been deleted
- **THEN** attribution is resolved from the platform's records and remains correct

#### Scenario: An unresolved namespace is still recorded

- **WHEN** a namespace is observed that does not correspond to a known deployment
- **THEN** its usage is recorded with no deployment attributed

#### Scenario: A database is not attributed by namespace

- **WHEN** a tenant database is observed in the shared cluster's namespace
- **THEN** it is attributed to the deployment its record names, not left unresolved as
  platform overhead
