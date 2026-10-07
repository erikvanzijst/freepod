## MODIFIED Requirements

### Requirement: Progress is derived from the ledger

The sampler SHALL determine where to resume from the ledger itself rather than from
separately held state, so that a crash, restart or redeployment cannot desynchronize
its position from what has been recorded.

The sampler MAY record from more than one measurement source. It SHALL hold a separate
position for each, derived from the samples of the metrics that source records and no
other writer records. Other writers, and the sampler's other sources, record into the
same ledger for windows a source may not have reached. Counting their samples would
move that source past windows it never recorded, and skip them permanently. A metric
that another writer also records, as builds record most container quantities, SHALL
NOT count toward a source's position.

Determining a source's position SHALL cost the same however many samples the ledger
holds and however far behind the source is, including when it has recorded nothing
yet.

#### Scenario: A crashed run resumes correctly

- **WHEN** the sampler is terminated mid-run and restarted
- **THEN** each source resumes from the last window present in the ledger for the
  metrics only it records, with no gap and no duplicate

#### Scenario: Another writer's samples do not advance the sampler

- **WHEN** a build's usage is recorded for a window the sampler has not yet recorded,
  for example while its measurement source is unavailable
- **THEN** the sampler still records that window once it can

#### Scenario: One source's progress does not advance another

- **WHEN** container usage has been recorded through 15:00 but database sizes only
  through 12:00
- **THEN** database sizes resume from 12:00, not from 15:00

#### Scenario: A new source does not scan the ledger

- **WHEN** a source that has recorded nothing yet is added to a ledger holding millions
  of samples
- **THEN** finding its position takes a constant number of index lookups, not a scan of
  the samples recorded by other sources
