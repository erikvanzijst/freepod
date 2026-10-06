## Context

See `proposal.md` for motivation; the specs carry the requirements. Facts that shape the
approach:

- **The measurement exists.** `postgres_exporter` runs as a sidecar of
  `caelus-tenant-postgres` in each environment's namespace (d1ab818) and publishes
  `pg_database_size_bytes{datname}`, from `pg_database_size()`. Prometheus scrapes it every
  60 s through `kubernetes-service-endpoints`, which stamps `namespace` with the Service's
  namespace (`caelus` or `caelus-dev`). On 2026-10-06 the 15 prod series matched
  `deployment_database.size_bytes` to the byte. History starts about 12:44 UTC that day;
  Prometheus retains 10 days.
- **The sampler is built around one source.** `sample_once` walks pending windows from
  one resume position and stops at the first unusable window. `last_recorded_window`
  already filters to `container` subjects so that the build worker's samples cannot
  advance it (`record-build-usage` D9).
- **The report needs no change.** `query_usage` reports every `delta` metric that has a
  rate, joins subjects to deployments by `deployment_id`, and prices at read time.
- **Two settings already exist:** `prometheus_base_url`, which the OpenCost source's trust
  check already uses, and the shared window, settle, lookback and per-pass limits.

## Goals / Non-Goals

**Goals:**

- Add a second source without changing how the OpenCost source behaves, and keep each
  source's failures confined to that source.
- Keep attribution and environment scoping in the platform database, as for containers.

**Non-Goals:**

- A general plugin framework for sources. Two sources need a shared shape, not a
  registry.
- Object storage. This shape is meant to take it next, but nothing here builds it.
- Changing `recorded_through` (see Risks).

## Decisions

### D1: Read Prometheus directly, for this axis only

`add-usage-ledger` chose the OpenCost API over direct PromQL because a hand-written
container query mishandles restarts, pod churn and partial pod lifetimes. None of that
applies here: there is one long-lived series per database, named by a stable key, and
nothing to join. OpenCost has no view of a database's size at all, so the choice is
Prometheus or nothing.

*Alternative considered:* the database housekeeping worker writes samples from its own
60-second `pg_database_size()` reads. Rejected: it has no history, so any outage of that
process is a permanent gap; it couples metering to quota enforcement, which the separate
usage worker exists to avoid; and it would build the integration over time that
`avg_over_time` already does.

### D2: One query per window for the values, one for trust

For a window `[s, e)`, at evaluation time `e`:

- **Values:** `avg_over_time(pg_database_size_bytes{namespace="<ns>"}[<window>s])`.
  Byte-hours are the average multiplied by the window's length in hours. Prometheus's
  range is `(e − window, e]`, the same convention the OpenCost trust check already uses.
- **Trust:** `count(count_over_time(pg_database_size_bytes{namespace="<ns>"}[<window>s]))`.
  Any series at all, including `postgres` and `template1`, proves the exporter published
  during the window. An empty result makes the window unusable.

Neither query selects databases by name. Which databases are tenants' is answered by the
platform's records (D4), and a `datname` pattern would re-derive membership from the
naming convention that `deployment_database` stores `db_name` precisely to avoid: a
changed prefix would silently stop metering every existing database. A pattern would
also need escaping for a PromQL string literal, which is not Python's `re.escape` (a
prefix such as `dpl.` escaped that way is a 400 from Prometheus). The cost of not
filtering is the server's own three databases per window, which D4 discards.

The `namespace` filter is what keeps the other environment's exporter from vouching for
this one (spec: *Another environment's measurements do not stand in*). It cannot come from
the database's own records, so it is a setting (D7).

A partly covered window is recorded at the average of what was published, as agreed.
Requiring full coverage would let every exporter or Postgres restart stall the source for
an hour; size moves slowly enough that the average is a fair estimate. This sits within
the ledger's rule against partial windows: the window is closed and settled; only its
measurements are sparse.

`pg_up 0` (exporter running, database unreachable) yields no size series, so it behaves
exactly like an exporter outage.

### D3: A source is a small object; the pass runs each one independently

Extract what is source-specific from `sampler.py` into a narrow shape:

- the subject kind it records, which scopes its resume position;
- `read(window) -> rows | None`, where `None` means unusable.

`sample_once` keeps its window arithmetic (`pending_windows`, `align`, the settle
allowance, `max_windows`) and runs it once per source, each from its own position, each
stopping at its own first unusable window, each committing per window. An exception from
one source is caught and logged at the source boundary, so the other source still runs in
the same pass.

`last_recorded_window(session, kind)` takes the kind as a parameter. The OpenCost source
passes `container`, which preserves today's behavior exactly.

*Alternative considered:* a second worker process. Rejected: the cadence, the settle
allowance and the blast radius are the same as the OpenCost source's, and a process per
axis would multiply rollout entries (`scripts/rollout.sh`) for nothing.

### D4: Subjects and attribution

One subject per database: kind `database`, `ref` = `deployment_database.db_name`,
`namespace` = the tenant cluster's namespace, `deployment_id` from the same row.
`upsert_subject` is reused unchanged.

Per window, the source loads `deployment_database` joined to `deployment` once, keyed by
`db_name`, and keeps only series whose `datname` is in it. That join is the only thing
that selects tenant databases (D2), and it gives attribution
(spec: *Attribution comes from the platform's record of the database*) and, as a side
effect, a second guarantee that only this environment's databases are recorded.

The database name is derived from the deployment id and stored on a row unique per
deployment, so a deployment has exactly one database subject for its lifetime.

### D5: Deletion is read from `deployment.deleted_at`

A database is skipped for a window when its deployment's `deleted_at` is set and earlier
than the window's end. `deployment_database.purge_after` is not used: it is the deletion
time plus a configurable grace period, so deriving the deletion from it would break when
the grace period changes.

Because the rule compares against the window rather than against "now", catch-up after an
outage still records the windows that ended before the deletion.

### D6: Quantities, the allowance and the rate

One migration adds the two catalog rows and the rate:

| name | axis | unit | kind | role | rate |
|---|---|---|---|---|---|
| `db_byte_hours` | storage | byte_hours | delta | usage | €0.000171 per 2^30, from 2026-10-06 |
| `db_allowance_byte_hours` | storage | byte_hours | delta | allocation | none |

`db_allowance_byte_hours` is the plan's `database_bytes` × window hours. The ledger's
*Consumption and allowance are recorded side by side* requirement calls for it, and it is
what will later turn "how full is this database" into a query rather than a join against
plan history. Being unpriced, it never appears in a report. It is read from the plan in
effect when the window is recorded; plan history is not consulted. A deployment whose
plan declares no allowance records no allowance row rather than failing the window.
`resolve_quota_bytes` raises in that case, which is right for provisioning but not here.

**The rate is market-based, and CPU and memory are not.** CPU (€0.015437/core-hour) and
RAM (€0.002069/GiB-hour) mirror the OpenCost cost model, a Hetzner CCX33 equivalent at
cost, whose storage figure is €0.00007836/GiB-hour (≈ €0.057/GiB-month). Database storage
is priced instead against managed-Postgres offerings, per GB-month: Supabase $0.125 (8 GB
included on Pro); AWS RDS PostgreSQL gp3 Single-AZ $0.137 in eu-central-1 and $0.115 in
us-east-1 (from the AWS price-list API); DigitalOcean $0.115–0.215; Scaleway Block 5K
€0.0993 and Block 15K €0.1489; Neon $0.35. €0.125/GiB-month sits between Supabase and RDS
Frankfurt. It deliberately covers more than disk: the tenant cluster's server and pooler
are recorded as unattributed platform overhead, and this is the only place a tenant pays
toward them. The breakdown by resource therefore shows CPU and Memory at cost next to
Database at a market price. That is acceptable while nothing is billed, but the three
cannot be read as comparable margins.

`€0.125 / 730 h = €0.00017123`, stored as `0.000171`: €0.12483 per GiB-month.

### D7: One new setting

`usage_tenant_db_namespace`, from `CAELUS_USAGE_TENANT_DB_NAMESPACE` in the shared `api`
ConfigMap, set to `var.namespace`. When it is empty, the database source is disabled and
says so once at startup. It must not run unscoped, because an unscoped trust check would
accept the other environment's exporter (D2).

The metric name `pg_database_size_bytes` is a constant in the source module, with a
comment naming `tf/app/caelus/tenant-db.tf` as its other end. The database naming prefix
is not used at all (D2).

### D8: The UI is one label

`METRIC_LABELS` in `ui/src/components/usage/usageBreakdowns.ts` gains
`db_byte_hours: 'Database'`. Its key order is the ranking `colorSeries` uses, so Database
takes the third palette slot (aqua) for good, after CPU and Memory. Nothing else in the UI
is metric-specific.

## Risks / Trade-offs

- **[The exporter sidecar shares the database pod's readiness]** If it crash-loops,
  tenants lose their databases. This was accepted when it was deployed (d1ab818). → It
  survives an unreachable database, has no probes, and has a memory limit of eight times
  its footprint.
- **[`recorded_through` is ledger-wide]** It reports the newest window of any subject, so
  with database recording stalled it still shows container progress. → Accepted for now:
  the gap is visible in the database series itself, and making it per source would change
  the report contract. Revisit with object storage.
- **[A 10-day recovery bound]** Same as CPU and memory: beyond Prometheus's retention, a
  missed window is gone. → Unchanged exposure; the per-pass limit replays at most 24
  windows per tick, enough to clear 10 days in about 10 ticks.
- **[Averaging over gaps can overstate]** A database dropped and re-created inside a gap
  is averaged at the sizes either side. → Bounded by one window, and sizes move slowly.
- **[First run]** The source's position is empty, so it starts from the bounded six-hour
  lookback. Windows before the exporter existed are unusable, so the first pass stops at
  the first one. → It advances once the lookback falls inside the exporter's history.
  This is self-correcting within six hours of deploy, and moot once the change ships
  later than that.

## Migration Plan

1. Migration: catalog rows and rate. Purely additive. Rollback drops the three rows,
   which requires deleting any samples first; samples are only written once step 2
   ships.
2. Deploy the API image and set `CAELUS_USAGE_TENANT_DB_NAMESPACE` through Terraform. The
   usage worker picks up the second source on restart.
3. Verify on dev: after the next settled window, every `deployment_database` row without
   a deleted deployment has a `db_byte_hours` sample whose value / 2^30 matches the
   Prometheus average, and Settings → Usage → By resource shows Database.
4. Repeat on prod.

*Rollback:* unset the namespace setting, which disables the source without a deploy, or
roll back the image. Samples already written stay valid.
