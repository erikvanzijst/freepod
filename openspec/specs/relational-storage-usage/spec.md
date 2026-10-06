# relational-storage-usage Specification

## Purpose

How a tenant database's size becomes usage ledger samples — which databases, measured
how, over which windows and attributed to whom — and how that usage is priced and shown
alongside CPU and memory.

## Requirements

### Requirement: A tenant database's size is recorded for every closed window

The system SHALL record, for every database a deployment holds on the tenant database
cluster, the database's size integrated over each closed and settled window: its average
size across the window multiplied by the window's length, in byte-hours.

The recorded size SHALL be the database's size as the server reports it, including the
space every database occupies when empty. The system MUST NOT subtract a baseline.

Windows SHALL be aligned to the same grid, length and settling allowance as every other
quantity the sampler records, so a database's usage sums with its deployment's CPU and
memory over any period.

#### Scenario: A database of constant size

- **WHEN** a database is 2 GiB throughout a one-hour window
- **THEN** 2 GiB-hours are recorded for that database and window

#### Scenario: An empty database is still recorded

- **WHEN** a deployment's database holds no tables
- **THEN** its size as reported by the server is recorded, not zero

#### Scenario: The current window is not recorded

- **WHEN** recording runs part-way through a window
- **THEN** that window is not recorded until it has closed and settled

### Requirement: The database's allowance is recorded alongside its size

For every window in which a database's size is recorded, the system SHALL also record
the database allowance of the deployment's plan, integrated over the window in
byte-hours, as an allowance rather than as consumption.

The allowance is the plan in effect when the window is recorded.

#### Scenario: Size and allowance are both present

- **WHEN** a database's size is recorded for a window
- **THEN** its plan's allowance is recorded for the same subject and window, and the two
  can be summed independently

### Requirement: A window is recorded only if it was measured

The system SHALL treat a window as unusable when the size measurements for its own
environment's tenant database cluster published nothing at all over that window. An
unusable window MUST NOT be recorded for any database and MUST NOT advance this
measurement's progress.

A window the measurements covered only in part SHALL be recorded, at the average of the
measurements that were published.

A database with no measurement in an otherwise usable window SHALL have nothing recorded
for that window, rather than zero.

The measurements of another environment's cluster MUST NOT make a window usable for
this one.

#### Scenario: An exporter outage does not record zeros

- **WHEN** no size measurement was published for the whole of a window
- **THEN** no database is recorded for that window, and the window is recorded on a later
  run once measurements cover it

#### Scenario: A brief gap is averaged over

- **WHEN** measurements were published for 50 of a window's 60 minutes
- **THEN** each database is recorded at the average of its published sizes over the
  whole window

#### Scenario: Another environment's measurements do not stand in

- **WHEN** this environment's measurements are absent for a window but another
  environment's are present
- **THEN** the window is unusable for this environment

#### Scenario: A database created mid-window

- **WHEN** a database first appears in the measurements part-way through a window
- **THEN** it is recorded at the average of its sizes over the part it was measured

### Requirement: Attribution comes from the platform's record of the database

A database SHALL be attributed to the deployment that the platform's own record of the
database names. The system MUST NOT take attribution from metadata supplied by the
measurement source.

A database the environment's records do not know SHALL NOT be recorded. This also keeps
each environment to its own databases where environments share a measurement store.

#### Scenario: A database's usage appears under its deployment

- **WHEN** usage is reported for the owner of a deployment with a database
- **THEN** the database's usage is included under that deployment, its application and its
  product

#### Scenario: An unknown database is not recorded

- **WHEN** a measured database does not correspond to a database this environment's
  records hold
- **THEN** it is not recorded

### Requirement: A deleted deployment's database stops accruing at deletion

The system SHALL NOT record a database for a window that ends after its deployment was
deleted, even though the database remains on the cluster until its purge.

Windows that ended before the deletion SHALL still be recorded, including when they are
recorded late.

#### Scenario: The purge grace period is not recorded

- **WHEN** a deployment is deleted at 14:20 and its database is purged days later
- **THEN** no window ending after 14:20 is recorded for that database

#### Scenario: Catch-up still records the time before deletion

- **WHEN** recording was unavailable from 10:00, the deployment was deleted at 14:20, and
  recording resumes at 16:00
- **THEN** the windows 10:00–14:00 are recorded for that database, and 14:00–15:00 is not

### Requirement: Database storage is priced and shown as its own resource

Database size SHALL be priced at a rate of €0.000171 per GiB-hour (about €0.125 per
GiB-month), effective for windows starting on or after 2026-10-06. The allowance SHALL
NOT be priced.

The usage the system reports per account, across accounts and through the operator CLI
SHALL include priced database usage with no change to how those reports are requested.
The plan's database allowance MUST NOT be netted out of it.

In the usage UI's breakdown by resource, database usage SHALL appear as a resource named
"Database", alongside CPU and Memory.

#### Scenario: A month of database storage is priced

- **WHEN** a database is 1 GiB throughout a 730-hour period after 2026-10-06
- **THEN** its reported cost for the period is €0.12483

#### Scenario: Usage within the allowance is still priced

- **WHEN** a database is smaller than its plan's allowance
- **THEN** its full size is priced, not only the part above the allowance

#### Scenario: Database appears next to CPU and Memory

- **WHEN** an owner views their usage broken down by resource
- **THEN** Database is shown as a resource alongside CPU and Memory
