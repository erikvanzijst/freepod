## Context

See `proposal.md` for motivation. This document records the decisions and the
alternatives weighed.

Three facts, established by measuring the live cluster in September 2026, shape
everything here:

- **OpenCost is a two-stage pipeline.** An exporter loop computes `max(request, usage)`
  per container per minute and publishes it as its own Prometheus gauges; `/allocation`
  reads those back. Prometheus must scrape OpenCost or `cpuCoreHours` silently equals
  the request. That scrape is in place.
- **Prometheus retains ten days.** Beyond that, nothing reconstructs a missed window.
- **Only the SSH sidecar declares resource requests today** (`cpu: 10m`,
  `memory: 32Mi`); application containers declare none, so they run BestEffort and the
  `max(request, usage)` floor is nominal.

## Goals / Non-Goals

**Goals:**

- A record that can be billed from later without being rewritten.
- Measurement decisions that survive a change of source, of cadence, or of axis.
- Enough recorded alongside the billable quantity to audit it after the fact.

**Non-Goals:**

- Any pricing, rate, invoice or currency concern (see `proposal.md`).
- Storage collectors. The model accommodates them; this change does not build them.
- Reconciling the ledger against OpenCost's own cost figures. Those are not consumed.

## Decisions

### Source the OpenCost API, not Prometheus directly

Its query layer is ~3,000 lines handling cAdvisor label drift, pod lifetimes and
partial windows. A hand-written equivalent is small only while it is naive.

*Alternative considered:* direct PromQL. Rejected as a false economy — the queries that
look simple are the ones that silently mis-handle restarts and short-lived pods.

*Consequence:* the ledger depends on OpenCost's contract and its scrape loop. Mitigated
by recording the components, below.

### Record `cpuCoreHours` and `ramByteHours` as the billable quantities

OpenCost applies `max(request, usage)` **per container per minute**. Summing
per-container maxima necessarily exceeds the max of the sums, and per-minute maxima
capture peaks that a window average smooths away.

*Alternative considered:* record only the usage and request averages and take the max
at invoice time. Rejected because it computes the max at a coarser granularity and so
systematically undercounts — it cannot reproduce the figure.

*Also recorded:* the usage, request and limit averages, as diagnostics. They are what
tells us whether request floors need adjusting, and they are the means of detecting a
window collected while OpenCost's exporter was down.

### One narrow table plus a catalog, not a column per quantity

Adding an axis becomes an insert rather than a migration, which is what lets storage
arrive later without touching the schema. The catalog is a table with a foreign key
rather than a code enum: in a narrow table an unconstrained name is the main
correctness risk, because a typo creates a new series and silently drops rows out of
every total.

*Alternative considered:* a wide table per axis. Rejected: it makes every new quantity
a migration, and cross-axis queries a union.

### `numeric`, not integers with a scale factor

OpenCost's values are fractional (`cpuCoreHours: 9e-05`, `minutes: 11.43584`). Integers
would require an invented scale, and a ledger where a reader must remember the factor
will eventually be summed wrong. `numeric` is exact decimal, so totals are exact and
the stored value matches the source.

### Subjects are containers, identified by controller

`<namespace>/<controllerKind>/<controller>/<container>` is stable across pod restarts,
where pod names are not. Container granularity is what allows the platform-injected SSH
sidecar to be separated from the application later, which is a real pricing question.

*Alternative considered:* pod-level subjects. Rejected: churn multiplies subject rows
without adding billing information.

### The resume position is derived from the ledger

One source of truth, self-healing after a crash, and no second thing to keep in sync.

*Alternative considered:* a run/provenance table recording each sampling run and the
OpenCost version that produced it. Deferred deliberately — it is the right answer for
attributing a semantic change to a version upgrade, but the system is too volatile to
carry it yet.

### A separate worker process

Cadence, failure modes and blast radius differ from reconciliation and database
housekeeping, and the ledger should keep recording when those break.

*Alternative considered:* another tick inside `db-worker`. Rejected on blast radius.

### Sub-hourly tick, hourly windows

Only one run an hour finds work; the rest return immediately. The short tick is a retry
mechanism, not a resolution choice: a failed run recovers in minutes instead of an hour,
and no separate retry machinery is needed because the loop is idempotent.

### Postgres, with TimescaleDB as a known exit

Measured at ~250 MB/year at current scale with these indexes. A benchmark of one year
of synthetic samples gave 251 MB on Postgres 16 and 36 MB on a compressed TimescaleDB
hypertable; the natural primary key keeps that exit open, since hypertables require the
time column in every unique index.

*Alternative considered:* a time-series database as the store of record. Rejected: this
data is a ledger, and metrics stores are built to lose precision gracefully — retention,
downsampling, no transactional upserts.

### A btree on the window, not BRIN

BRIN would be a tenth the size and adequate for range scans, but cannot answer the
`max()` the resume position depends on, which would leave that query scanning the table.

## Data model

```sql
-- What quantities exist, and how each one aggregates.
CREATE TABLE usage_metric (
    id     smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name   text NOT NULL UNIQUE,
    axis   text NOT NULL,   -- cpu | memory | network | storage | runtime
    unit   text NOT NULL,   -- core_hours | cores | byte_hours | bytes | seconds
    kind   text NOT NULL,   -- delta (accrued in the window) | gauge (held across it)
    role   text NOT NULL    -- usage | allocation
);

-- What is being measured. `ref` is stable for the subject's lifetime; a
-- re-created volume or bucket is a new subject, not the same one.
CREATE TABLE usage_subject (
    id            integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind          text NOT NULL,   -- container | pv | bucket | database | node
    ref           text NOT NULL,
    namespace     text,
    deployment_id uuid REFERENCES deployment (id),   -- NULL for platform namespaces
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (kind, ref)
);

CREATE TABLE usage_sample (
    subject_id       integer     NOT NULL REFERENCES usage_subject (id),
    metric_id        smallint    NOT NULL REFERENCES usage_metric (id),
    window_start     timestamptz NOT NULL,
    interval_seconds integer     NOT NULL,
    observed_at      timestamptz NOT NULL,
    value            numeric     NOT NULL,
    PRIMARY KEY (subject_id, metric_id, window_start)
);

-- Serves the sampler's resume position (max(window_start)) and period scans.
CREATE INDEX ix_usage_sample_window ON usage_sample (window_start);

-- The billing join: every subject belonging to a deployment.
CREATE INDEX ix_usage_subject_deployment ON usage_subject (deployment_id)
    WHERE deployment_id IS NOT NULL;

-- The sampler resolves namespace -> subject on every row it writes.
CREATE INDEX ix_usage_subject_namespace ON usage_subject (namespace);

-- One additive quantity regardless of axis or metric kind.
CREATE VIEW usage_amount AS
SELECT s.subject_id, s.window_start, s.interval_seconds,
       m.name AS metric, m.axis, m.role,
       CASE m.kind WHEN 'gauge' THEN s.value * s.interval_seconds ELSE s.value END
         AS amount
FROM usage_sample s JOIN usage_metric m ON m.id = s.metric_id;
```

The primary key covers the two hottest paths — one series over time, and the
idempotent upsert — which is why no further index on `usage_sample` is needed.

## Ledger to OpenCost mapping

One `GET /allocation?window=<from>,<to>&step=1h&aggregate=container` per run. Each
allocation in the response becomes one `container` subject and the rows below.

| Ledger metric | OpenCost field | unit | kind | role |
|---|---|---|---|---|
| `cpu_core_hours` | `cpuCoreHours` | core_hours | delta | usage *(billable)* |
| `cpu_usage_cores_avg` | `cpuCoreUsageAverage` | cores | gauge | usage |
| `cpu_request_cores_avg` | `cpuCoreRequestAverage` | cores | gauge | allocation |
| `cpu_limit_cores_avg` | `cpuCoreLimitAverage` | cores | gauge | allocation |
| `ram_byte_hours` | `ramByteHours` | byte_hours | delta | usage *(billable)* |
| `ram_usage_bytes_avg` | `ramByteUsageAverage` | bytes | gauge | usage |
| `ram_request_bytes_avg` | `ramByteRequestAverage` | bytes | gauge | allocation |
| `ram_limit_bytes_avg` | `ramByteLimitAverage` | bytes | gauge | allocation |
| `network_transmit_bytes` | `networkTransferBytes` | bytes | delta | usage |
| `network_receive_bytes` | `networkReceiveBytes` | bytes | delta | usage |
| `pv_byte_hours` | `pvByteHours` | byte_hours | delta | allocation |
| `running_seconds` | `minutes` x 60 | seconds | delta | usage |

Notes on the mapping:

- Both memory quantities resolve to **working set**. OpenCost queries exactly two
  memory metrics — `container_memory_working_set_bytes` and its own
  `container_memory_allocation_bytes`, whose `used` input is that same working set —
  so `ramByteHours = max(request, working set)`, integrated.
- Subject identity comes from `properties`: `namespace`, `controllerKind`,
  `controller`, `container`. `namespaceLabels` also returns the owner, product and
  environment labels, which are useful for cross-checking but are **not** the source
  of attribution; the platform database is, because labels vanish with the namespace.
- `running_seconds` is what distinguishes a quiet hour from a short one: a container
  that lived 11 of 60 minutes reports `minutes: 11.43584`, and
  `cpuCoreHours = cpuCores x minutes/60`.
- `pv_byte_hours` carries `role = allocation` because it is requested capacity, not
  consumption — PVC usage is not available from OpenCost. It is recorded because it
  arrives free in the same response. Volumes not mounted by a running pod are
  attributed to a synthetic `__unmounted__` allocation with no namespace, so they
  reach no tenant.
- No cost field is consumed. `cpuCost`, `ramCost`, `totalCost` and the idle and
  adjustment fields are deliberately ignored.

## Risks / Trade-offs

- **An OpenCost outage silently degrades the billable quantity to the request.** Its
  exporter loop stops, so the allocation series is absent for those minutes and a later
  replay falls back to the request — no error, no obvious symptom. → Both components are
  recorded, so a window can be audited after the fact by comparing the billable value
  against the higher of usage and request; undercharging, never over.
- **A Prometheus outage is unrecoverable after ten days.** → Lag must be observable
  while recovery is still possible; raising retention as a recovery buffer is cheap and
  is a separate decision from where the record of truth lives.
- **OpenCost semantics can change across versions without the API changing.** → The
  chart version is pinned; a provenance table is the fuller answer and is deferred.
- **Request floors are nominal today**, so the billable quantity is effectively
  usage-only. Setting real floors is separate work, and is bounded by node headroom:
  4 cores allocatable against 2.59 already requested.
- **Both environments record shared platform namespaces**, double-counting overhead if
  the two ledgers are ever summed together. → Accepted: dev is never billed, and dev
  moves to its own cluster eventually, at which point it should count its own platform
  services.

## Migration Plan

Additive throughout; nothing reads the new tables.

1. Create the tables, indexes and view in one migration, and seed the catalog rows in
   the same migration so a deployment is never able to write an uncatalogued quantity.
2. Deploy the worker. Its first run finds an empty ledger, so the resume position must
   fall back to a bounded lookback rather than attempting the whole retention window in
   one request.
3. Verify against the dashboard: recorded quantities for a window should agree with the
   same window read from OpenCost.

*Rollback:* stop the worker. The tables can be left in place, since nothing reads them;
dropping them loses only the collected history.

## Open Questions

- Retention of the ledger itself, and its privacy implications, since usage tied to a
  user is personal data. Does not affect the schema.
- Whether to raise Prometheus retention purely as a recovery buffer.
- The bounded lookback for a first run, and the lag threshold at which the sampler is
  reported as behind. Both are configuration, resolvable during implementation.
