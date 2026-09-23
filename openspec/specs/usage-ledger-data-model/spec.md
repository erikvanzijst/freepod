# usage-ledger-data-model Specification

## Purpose
Defines the durable record of what deployments consume: the catalog of quantities the
platform measures, the subjects those quantities are attributed to, and the rules that
make a sample trustworthy enough to bill from later.

## Requirements

### Requirement: Every recorded quantity is catalogued

The system SHALL maintain a catalog of measurable quantities. Each entry MUST declare
a unique name, the axis it belongs to, its unit, its kind (a value held across the
window, or an amount accrued within it) and its role (consumption, or an allowance
such as a request, limit or quota).

A sample MUST reference a catalog entry. A quantity that is not catalogued MUST NOT be
recordable. Adding a new quantity MUST NOT require changing the shape of the tables.

#### Scenario: An uncatalogued quantity is rejected

- **WHEN** a sample is written naming a quantity that has no catalog entry
- **THEN** the write is rejected

#### Scenario: A new quantity is added without schema change

- **WHEN** a new axis such as storage is introduced
- **THEN** its quantities are added as catalog entries and recorded against existing
  tables, with no change to table definitions

### Requirement: Subjects carry attribution, and it survives deletion

The system SHALL record each quantity against a subject: the thing that consumed it.
A subject MUST declare its kind and a reference that is stable for that subject's
lifetime, and MUST be unique on that pair.

A subject MUST carry the namespace it was observed in and, where one resolves, the
deployment that owns it. Attribution MUST remain resolvable after the deployment is
deleted. A subject that resolves to no deployment — a platform namespace — MUST still
be recorded, with no deployment attributed.

Subject records MAY be updated as attribution improves; samples MUST NOT.

#### Scenario: Usage is attributed to the owning user

- **WHEN** usage is summed for a user over a period
- **THEN** every subject whose namespace resolves to one of that user's deployments is
  included

#### Scenario: A deleted deployment keeps its history

- **WHEN** a deployment is deleted and its usage is queried for a past period
- **THEN** the samples remain attributed to that deployment and its owner

#### Scenario: Platform overhead is recorded

- **WHEN** a namespace belongs to the platform rather than a tenant
- **THEN** its subjects are recorded with no deployment attributed, and its usage is
  queryable as unattributed overhead

#### Scenario: A re-created volume is a distinct subject

- **WHEN** a persistent volume is destroyed and a new one created for the same
  deployment
- **THEN** the new volume is recorded as a new subject, and both remain attributed to
  the same deployment through their namespace

### Requirement: Samples are window-aligned and self-describing

Each sample SHALL record the start of the window it covers, the length of that window,
and the time the measurement was taken. The window start MUST be aligned to the window
length.

A sample MUST be interpretable without reference to any other sample or to
configuration. Changing the sampling cadence MUST NOT invalidate or require rewriting
existing samples.

#### Scenario: Cadence changes without breaking history

- **WHEN** the sampling interval is changed by an operator
- **THEN** samples written before and after the change are both interpretable, and
  totals computed across the change remain correct

### Requirement: The ledger is append-only and idempotent

A sample SHALL be uniquely identified by its subject, quantity and window start.
Re-recording a window that is already present MUST leave the stored value unchanged
and MUST NOT raise an error.

Recorded samples MUST NOT be modified or deleted as part of normal operation.

#### Scenario: A replayed window changes nothing

- **WHEN** a window that has already been recorded is recorded again
- **THEN** the stored values are unchanged and the operation succeeds

### Requirement: Only complete, observed windows are recorded

The system MUST NOT record a window that is still in progress, and MUST NOT record a
partial window.

An absent sample MUST mean the quantity was not measured. A recorded zero MUST mean
the quantity was measured and found to be zero. The system MUST NOT record zero for a
window whose measurement was unavailable.

#### Scenario: The current window is not recorded

- **WHEN** sampling runs part-way through a window
- **THEN** that window is not recorded, and the most recent recorded window is the last
  complete one

#### Scenario: An unavailable measurement is absent, not zero

- **WHEN** the measurement source cannot answer for a window
- **THEN** no sample is recorded for that window, rather than a sample of zero

### Requirement: Quantities are recorded exactly, and carry no money

Recorded values SHALL be stored as exact decimal quantities. The system MUST NOT round
fractional measurements to integers, and MUST NOT require callers to apply a scale
factor to interpret a value.

The ledger MUST NOT store monetary amounts, rates or currency. What a quantity costs
is decided outside this record.

#### Scenario: A fractional measurement is preserved

- **WHEN** a measurement reports a fractional quantity
- **THEN** the stored value equals the reported value, without rounding

#### Scenario: Historical usage can be re-priced

- **WHEN** rates change and a past period is re-evaluated at the new rates
- **THEN** the recorded quantities are unchanged and support the new calculation

### Requirement: Consumption and allowance are recorded side by side

For each axis where an allowance exists, the system SHALL record both what was consumed
and what was allowed, as separate catalogued quantities against the same subject and
window.

#### Scenario: Requests and usage are both available

- **WHEN** a container's CPU and memory are recorded for a window
- **THEN** both the consumed quantities and the requested and limited allowances are
  recorded, and either can be summed independently

### Requirement: Both metric kinds reduce to one additive quantity

The system SHALL expose recorded samples as a single additive amount per sample,
derived from the metric's kind: a value held across the window is multiplied by the
window length, and an amount accrued within the window is taken as recorded.

#### Scenario: Mixed kinds sum correctly

- **WHEN** an amount is totalled for a subject over a period spanning both metric kinds
- **THEN** each sample contributes its amount without the caller needing to know which
  kind it was
