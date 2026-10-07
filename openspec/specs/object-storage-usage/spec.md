# object-storage-usage Specification

## Purpose

How a deployment bucket's size becomes usage ledger samples: which buckets, measured
over which windows, attributed to whom, when they stop accruing, and how that usage is
priced and shown alongside CPU, memory and databases.

## Requirements

### Requirement: A bucket's size is recorded for every closed window

The system SHALL record, for every deployment bucket on its environment's Garage
instance, the bucket's size integrated over each closed and settled window. That is its
average published size across the window multiplied by the window's length, in
byte-hours.

The size SHALL be the bytes of the bucket's completed objects, as the bucket size
exporter publishes it.

Windows SHALL be aligned to the same grid, length and settling allowance as every other
quantity the sampler records.

#### Scenario: A bucket of constant size

- **WHEN** a bucket holds 2 GiB throughout a one-hour window
- **THEN** 2 GiB-hours are recorded for that bucket and window

#### Scenario: The current window is not recorded

- **WHEN** recording runs part-way through a window
- **THEN** that window is not recorded until it has closed and settled

### Requirement: Empty buckets are not recorded

A bucket whose average size over a window is zero SHALL have nothing recorded for that
window.

#### Scenario: A deployment that never uses its bucket

- **WHEN** a deployment's bucket holds nothing throughout a window
- **THEN** no sample is recorded for it in that window

#### Scenario: A bucket emptied mid-window

- **WHEN** a bucket holds 1 GiB for the first half of a window and nothing for the second
- **THEN** 0.5 GiB-hours are recorded for that window, and nothing for later windows
  while it stays empty

### Requirement: A window is recorded only if the exporter was running

The system SHALL treat a window as unusable when its own environment's bucket size
exporter published nothing at all over that window. An unusable window MUST NOT be
recorded for any bucket and MUST NOT advance this measurement's progress.

A window the exporter covered only in part SHALL be recorded, at the average of the
sizes that were published.

Another environment's exporter MUST NOT make a window usable for this one.

#### Scenario: An exporter outage does not record zeros

- **WHEN** the exporter published nothing for the whole of a window
- **THEN** no bucket is recorded for that window, and the window is recorded on a later
  run once measurements cover it

#### Scenario: An environment with no buckets still progresses

- **WHEN** the exporter ran throughout a window but the environment holds no deployment
  buckets
- **THEN** the window is usable, nothing is recorded, and progress advances past it

#### Scenario: Another environment's exporter does not stand in

- **WHEN** this environment's exporter published nothing for a window but another
  environment's did
- **THEN** the window is unusable for this environment

### Requirement: Attribution comes from the bucket's name, confirmed by the platform's records

A bucket SHALL be attributed to the deployment whose identifier its name carries
(`dep-<deployment id>`). That identifier SHALL be confirmed against this environment's
deployment records before anything is recorded.

A bucket whose name does not carry a well-formed deployment identifier, or whose
identifier this environment's records do not hold, SHALL NOT be recorded. It SHALL NOT
prevent the window's other buckets from being recorded.

The confirmation SHALL be made in bulk, for many buckets per round trip, so the database
work per window grows with the number of buckets divided by a fixed batch size, not with
the number of buckets.

#### Scenario: A bucket's usage appears under its deployment

- **WHEN** usage is reported for the owner of a deployment with object storage
- **THEN** the bucket's usage is included under that deployment, its application and its
  product

#### Scenario: An unknown bucket does not stall recording

- **WHEN** a `dep-` bucket names a deployment this environment's records do not hold
- **THEN** that bucket is not recorded, and every other bucket in the window is

### Requirement: A deleted deployment's bucket stops accruing at deletion

The system SHALL NOT record a bucket for a window that ends after its deployment was
deleted, even though the bucket remains in Garage afterwards.

Windows that ended before the deletion SHALL still be recorded, including when they are
recorded late.

#### Scenario: The expiry period is not recorded

- **WHEN** a deployment is deleted at 14:20 and its bucket drains over the following days
- **THEN** no window ending after 14:20 is recorded for that bucket

#### Scenario: Catch-up still records the time before deletion

- **WHEN** recording was unavailable from 10:00, the deployment was deleted at 14:20, and
  recording resumes at 16:00
- **THEN** the windows 10:00–14:00 are recorded for that bucket, and 14:00–15:00 is not

### Requirement: Object storage is priced and shown as its own resource

Bucket size SHALL be priced at €0.0000274 per GiB-hour (about €0.02 per GiB-month),
effective for windows starting on or after 2026-10-07. The plan's storage allowance
SHALL NOT be netted out of it.

The usage the system reports per account, across accounts and through the operator CLI
SHALL include priced object storage usage with no change to how those reports are
requested.

In the usage UI's breakdown by resource, object storage SHALL appear as a resource
named "Object storage", alongside CPU, Memory and Database.

#### Scenario: A month of object storage is priced

- **WHEN** a bucket holds 1 GiB throughout a 730-hour period after 2026-10-07
- **THEN** its reported cost for the period is €0.020002

#### Scenario: Object storage appears next to the other resources

- **WHEN** an owner views their usage broken down by resource
- **THEN** Object storage is shown as a resource alongside CPU, Memory and Database
