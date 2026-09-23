## Purpose

Defines the process that fills the usage ledger: how often it samples, which window it
is allowed to record, what it consumes from the measurement source, and how it behaves
when that source is unavailable.

## ADDED Requirements

### Requirement: Usage sampling runs as its own process

The platform SHALL run usage sampling as a process separate from reconciliation, build
execution and database housekeeping. Failure or unavailability of those processes MUST
NOT stop usage sampling, and failure of usage sampling MUST NOT affect them.

Running more than one instance MUST NOT corrupt the ledger or produce duplicate
samples.

#### Scenario: Housekeeping failure does not stop the ledger

- **WHEN** the database housekeeping process is unavailable
- **THEN** usage sampling continues to record windows

#### Scenario: Two instances produce one set of samples

- **WHEN** two sampler instances record the same window concurrently
- **THEN** the ledger contains one sample per subject, quantity and window

### Requirement: Sampling records whole, completed windows

The sampler SHALL record usage on fixed windows, aligned to the window length, and
MUST only record a window once that window has ended and its measurements have settled.

The sampler MUST allow for measurements that arrive after a window closes, and MUST NOT
record a window before that allowance has elapsed.

#### Scenario: The in-progress window is skipped

- **GIVEN** an hourly window and a sampling run part-way through the 14:00–15:00 hour
- **WHEN** the run executes
- **THEN** the latest window it records is 13:00–14:00, and no partial window is written

#### Scenario: Late measurements are not truncated

- **WHEN** a run executes immediately after a window closes
- **THEN** it waits for the settling allowance before recording that window

### Requirement: Progress is derived from the ledger

The sampler SHALL determine where to resume from the ledger itself rather than from
separately held state, so that a crash, restart or redeployment cannot desynchronize
its position from what has been recorded.

#### Scenario: A crashed run resumes correctly

- **WHEN** the sampler is terminated mid-run and restarted
- **THEN** it resumes from the last window present in the ledger, with no gap and no
  duplicate

### Requirement: Gaps are filled at full granularity

When the sampler has fallen behind, it SHALL replay the missed period at the configured
window granularity, producing the same windows a healthy run would have produced. It
MUST NOT collapse a missed period into a single wider window.

The sampler MUST bound the size of any single request to its measurement source so that
a long gap is recovered incrementally, with progress preserved as it goes.

#### Scenario: A day-long outage is replayed hour by hour

- **GIVEN** an hourly window and a sampler that has been down for 24 hours
- **WHEN** it resumes
- **THEN** 24 separate windows are recorded, not one 24-hour window

#### Scenario: Recovery makes durable progress

- **WHEN** a long catch-up is interrupted part-way
- **THEN** the windows already recorded are retained and the next run continues from
  there

### Requirement: The sampler records consumption, allowances and runtime per container

For each container in a window, the sampler SHALL record the billable CPU and memory
quantities, the consumed and allowed component quantities for both axes, network
transfer quantities, and how long the container was running within the window.

Runtime MUST be recorded so that a window in which a container ran briefly is
distinguishable from one in which it ran throughout.

#### Scenario: A short-lived container is distinguishable

- **WHEN** a container runs for part of a window
- **THEN** its recorded runtime reflects that, and its quantities are interpretable
  against it

#### Scenario: Billable and diagnostic quantities are both present

- **WHEN** a window is recorded
- **THEN** the billable quantity and the consumed and allowed components are all
  present for that subject and window

### Requirement: Attribution comes from the platform's own records

The sampler SHALL resolve a subject's owning deployment from the platform database,
using the namespace the subject was observed in. It MUST NOT treat metadata supplied by
the measurement source as authoritative for attribution.

A subject whose namespace does not resolve MUST still be recorded, with attribution
left unresolved and able to be completed later.

#### Scenario: Attribution survives the namespace disappearing

- **WHEN** usage for a past period is attributed after the namespace has been deleted
- **THEN** attribution is resolved from the platform's records and remains correct

#### Scenario: An unresolved namespace is still recorded

- **WHEN** a namespace is observed that does not correspond to a known deployment
- **THEN** its usage is recorded with no deployment attributed

### Requirement: Unavailable measurements do not advance progress

When the measurement source is unavailable, returns no data, or returns data the
sampler cannot trust for a window, the sampler MUST NOT record samples for that window
and MUST NOT advance its position past it.

The sampler MUST record nothing rather than record zero for a window it could not
measure.

#### Scenario: An unavailable source leaves no trace

- **WHEN** the measurement source cannot be reached
- **THEN** no samples are written, the resume position is unchanged, and the window is
  recorded on a later run

### Requirement: Falling behind is observable

Because measurements become unrecoverable once the upstream retention window passes,
the platform SHALL make the sampler's lag observable, and MUST surface it while
recovery is still possible.

#### Scenario: Lag is surfaced before data is lost

- **WHEN** the sampler's most recent recorded window falls behind the present by more
  than the configured threshold
- **THEN** the condition is reported while the missed windows are still recoverable
