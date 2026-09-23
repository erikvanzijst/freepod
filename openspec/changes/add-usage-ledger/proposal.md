## Why

Freepod sells discrete plan tiers chosen by hand. Moving to usage-based pricing
requires a durable record of what deployments actually consume, and that record has
to exist before any pricing decision, because every such decision — provisioned
versus consumed, which axes matter, what a plan floor is worth — is answerable from
data or not at all.

Nothing durable exists today. Measurement works (OpenCost is deployed and its
exporter loop is scraped; the `tenant-usage` dashboard validates the same numbers),
but Prometheus retains ten days, so every day without a writer is history that
cannot be reconstructed later.

## What Changes

- Add three tables — `usage_metric`, `usage_subject`, `usage_sample` — plus a
  `usage_amount` view that turns gauge and delta metrics into one additive quantity.
- Add a `caelus usage-worker` process that samples OpenCost's `/allocation` API on
  an hourly window and writes one row per subject, metric and window.
- Record CPU, memory and network quantities per container: the billable
  `cpuCoreHours` and `ramByteHours`, their usage/request/limit component averages,
  network transfer bytes, and container running time.
- Record platform namespaces as subjects with no deployment, so unattributed
  overhead is measurable rather than invisible.

Explicitly **not** in this change: pricing, rate tables, invoices, cost fields of any
kind, enforcement, quota changes, retention policy, and the storage axes (object,
relational, PVC/block). The data model accommodates storage without migration — a
new metric is an insert, a new subject kind is a value — but no storage collector is
specified here.

This change is additive. No existing behavior changes, nothing is removed, and
nothing reads the new tables.

## Capabilities

### New Capabilities

- `usage-ledger-data-model`: the metric catalog, subject identity and attribution,
  sample semantics (window alignment, self-describing intervals, append-only
  writes), and the additive view over both metric kinds.
- `usage-sampler-worker`: the `caelus usage-worker` process — its cadence, window
  discipline, cursor derivation, idempotency, the OpenCost fields it consumes and
  what it must do when its sources are unavailable.

### Modified Capabilities

None. The change adds tables and a process; no existing requirement changes.

## Impact

- **New code**: `caelus usage-worker` (a fourth worker process alongside `worker`,
  `build-worker` and `db-worker`), an OpenCost API client, and SQLModel definitions
  plus an Alembic migration for the three tables and the view.
- **New deployment**: one more Deployment in `tf/app/caelus`, sharing the API image
  and service account.
- **Hard dependency on OpenCost**, already deployed and scraped. Its `/allocation`
  contract becomes load-bearing: `cpuCoreHours` is `max(request, usage)` computed
  per container per minute by an exporter loop whose output Prometheus must ingest.
  Without that scrape the value silently degrades to the request.
- **Database growth**: roughly 250 MB per year at current scale, measured on
  Postgres 16 with the indexes this change adds.
- **No tenant-visible change.** Nothing is billed, enforced or displayed.
