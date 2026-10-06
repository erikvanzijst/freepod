## Why

A `custom` deployment's database occupies real disk on the shared tenant PostgreSQL
cluster, but none of it reaches the usage ledger: the ledger records only what OpenCost
reports, and OpenCost knows nothing about a database inside another pod. The tenant
cluster's own CPU and memory are recorded too, but as unattributed platform overhead,
so a tenant's database is invisible in every usage report. The ledger was designed to
take storage without a schema change, and the measurement now exists:
`postgres_exporter` (d1ab818) publishes every tenant database's size to Prometheus on
dev and prod, with Prometheus's retention as history.

## What Changes

- A new catalogued quantity, `db_byte_hours`: a database's size integrated over the
  window, on the storage axis, recorded as consumption.
- The usage worker gains a second measurement source alongside OpenCost: it reads each
  tenant database's size for a closed window from Prometheus and records it against a
  new `database` subject, attributed to its deployment through the platform's own
  database record.
- Each source keeps its own resume position and stops at its own gaps, so an exporter
  outage never stalls CPU and memory recording, and an OpenCost outage never stalls
  storage.
- A window in which this environment's exporter published nothing is unusable and is
  not recorded. A window it covered only partly is recorded at the average of what was
  published.
- A database whose deployment has been deleted stops accruing at deletion, while it
  waits out its purge grace period.
- `db_byte_hours` is priced at €0.000171 per GiB-hour (≈ €0.125 per GiB-month) from
  2026-10-06: a market-based baseline, not a cost-based one like CPU and memory.
- The usage UI's "By resource" breakdown shows **Database** alongside CPU and Memory.
  The API and `caelus get-usage` include it with no change, since they report every
  priced quantity.

## Capabilities

### New Capabilities

- `relational-storage-usage`: how a tenant database's size becomes usage ledger
  samples — which databases, measured how, over which windows, attributed to whom —
  and how that usage is priced and shown.

### Modified Capabilities

- `usage-ledger-data-model`: a subject may be a tenant database, attributed through the
  platform's record of that database.
- `usage-sampler-worker`: the sampler records from more than one measurement source,
  and each source's progress and availability are independent of the others'.

## Impact

- **Database:** one migration adding the `db_byte_hours` catalog entry and its rate. No
  change to table definitions.
- **Usage worker:** a Prometheus-backed source next to OpenCost, and a resume position
  scoped per subject kind (`sampler.last_recorded_window`).
- **Configuration:** a new setting naming the namespace whose exporter this environment
  reads, set from Terraform's `var.namespace`.
- **UI:** one label in `ui/src/components/usage/usageBreakdowns.ts`.
- **Depends on:** the `postgres_exporter` sidecar and its scrape (d1ab818), on both
  environments.
- **Not included:** object storage; netting a plan's database allowance out of the
  report; attributing the tenant cluster's CPU and memory to tenants; backfilling
  before the exporter existed (2026-10-06, about 12:44 UTC). Nothing is invoiced.
