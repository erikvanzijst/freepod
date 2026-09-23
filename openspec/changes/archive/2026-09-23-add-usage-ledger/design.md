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

*Consequence, measured:* OpenCost's answer for a closed window is not stable on re-read
when a controller's pods were replaced inside it. Verifying a window whose workload
changed mid-window will not reproduce the recorded numbers; verifying a quiet window
reproduces them exactly. This bounds what auditing a past bill can prove.

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

A benchmark of one year of synthetic samples gave 251 MB on Postgres 16 and 36 MB on a
compressed TimescaleDB hypertable; the natural primary key keeps that exit open, since
hypertables require the time column in every unique index.

**That 251 MB was wrong by 7.5x, and the error is instructive.** Measured on dev after
the sampler had run: 1744 KB for 12732 samples over 8 windows — 140.3 bytes per sample
including indexes, at 1592 samples per window, which projects to **1865 MB/year**. The
per-sample figure was right; the subject count was not. The benchmark counted tenant
containers alone (~18), while the ledger records 137: 18 dev tenants, 59 platform
namespaces, and 60 tenant namespaces belonging to *prod*, which shares this cluster.
Recording platform overhead was this change's own decision, and the estimate was never
resized to match it.

Still comfortably inside the node's disk, and it strengthens rather than weakens the
TimescaleDB exit.

*Alternative considered:* a time-series database as the store of record. Rejected: this
data is a ledger, and metrics stores are built to lose precision gracefully — retention,
downsampling, no transactional upserts.

### Unattributable is not unavailable

A window where the source answers fully but cannot identify the workload is recorded
against its namespace, marked unresolved, and the cursor advances past it.

A source that answers but cannot identify the workload has not failed to answer —
retrying cannot improve it, because the limitation is in the response rather than in
availability. Treating it as an outage is what turns it into a permanent stall: the
resume position is derived from the ledger, so a window that is never recorded is
retried forever.

Nothing is lost by recording it. Where the controller is unresolved OpenCost has
already merged that namespace's containers before the sampler sees them — immich's
`server` and `machine-learning` pods arrive as a single `main` row — so the degraded
subject records what arrived, rather than discarding detail we still had. The
namespace is what attribution actually needs, and it survives.

*Alternative considered:* bounded retries, then skip. Rejected: the attempt counter is
a second piece of state beside the cursor, which is what deriving the position from the
ledger exists to avoid, and `max(window_start)` cannot express "gave up on 06:00 but
recorded 07:00" anyway.

*Alternative considered:* a `usage_gap` table. Rejected: it is the provenance table
deferred above, arriving by another name, and it records that the sampler gave up
without answering when it should stop.

### Each environment records only its own tenants

Dev and prod share one cluster but not one database, so every prod namespace is
unresolvable to dev's sampler and would be recorded as unattributed usage — the same
physical container in two ledgers, attributed in one and anonymous in the other.
Measured before the filter: 60 of dev's 137 subjects were prod tenants.

The sampler therefore skips a tenant workload whose namespace label names another
environment. Platform namespaces carry no tenant label and are still recorded by both,
which is the double-count below that the shared cluster makes unavoidable.

**This does not contradict attribution coming from the platform database.** That rule
exists because labels vanish with the namespace and a past period must stay
attributable long afterwards. Deciding whether to *sample* is a different question,
asked while the namespace exists by definition. The label chooses what to look at; it
never decides who owns what.

*Alternative considered:* record them unattributed and let whoever sums the ledgers
exclude them. Rejected — it needs a reader to know which namespaces were foreign at
the time, which is exactly the knowledge that decays.

*Consequence:* a tenant namespace with no environment label is recorded rather than
skipped, so a missing label cannot silently drop real usage. On a shared cluster that
means such a namespace is double-counted until it is labelled.

### A window whose measurements are untrustworthy is not recorded

Distinct from the above, and the reason the two are separate decisions: a window can be
fully attributable and still carry wrong numbers.

When OpenCost's own metrics are not being scraped, `/allocation` still answers, but
`cpuCoreHours` silently falls through to the request — the `max(request, usage)` floor
loses its first operand. So before recording a window the sampler asks Prometheus
whether `container_cpu_allocation` has any samples covering it, and records nothing if
it does not. Measured across the boundary: the pre-scrape hour returns no series at
all, the next healthy hour returns 126.

**This is a health check, not a measurement.** It computes no quantity, reads no
allocation and touches none of the label-drift and pod-lifetime handling that
"Source the OpenCost API, not Prometheus directly" exists to stay out of. It asks only
whether the pipeline's first stage ran. The cost is that the sampler needs a Prometheus
endpoint alongside OpenCost's.

*Alternative considered:* infer it from the numbers — reject a window where every entry
reports `cpuCoreHours == cpuCoreRequestAverage x hours`. Rejected because it is a
coincidence test that stops holding. Its safety rests on most containers declaring no
CPU request, so that the equality implies billing zero against real usage; once every
product container has a request (#132), a quiet night hour satisfies it legitimately
for every entry and a healthy window is discarded as unmeasured.

*Alternative considered:* reject a window where any entry reports `cpuCoreHours == 0`
while usage is non-zero. Sharper — billing zero against measured usage is impossible
when the operand is present, so it detects rather than infers — and it separates
cleanly today (55 pre-scrape, 0 in every healthy window). Rejected for the same reason:
post-#132, a missing operand yields `request x hours` rather than zero for every
container, so nothing trips it. It fails open where the other fails closed, and neither
survives requests becoming universal.

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
    first_seen_at timestamp NOT NULL DEFAULT now(),
    last_seen_at  timestamp NOT NULL DEFAULT now(),
    UNIQUE (kind, ref)
);

CREATE TABLE usage_sample (
    subject_id       integer     NOT NULL REFERENCES usage_subject (id),
    metric_id        smallint    NOT NULL REFERENCES usage_metric (id),
    window_start     timestamp   NOT NULL,
    interval_seconds integer     NOT NULL,
    observed_at      timestamp   NOT NULL,
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

One `GET /allocation?window=<from>,<to>&step=1h&aggregate=namespace,controllerKind,controller,container`
per run. Each allocation in the response becomes one `container` subject and the rows
below.

**The aggregation must name all four fields.** `aggregate=container` groups by container
name across every namespace and drops any property the group does not share, so a
container named `ssh` returns one row for the whole cluster with no `namespace` at all.
It looks correct for uniquely-named containers, which is exactly how it survived review.

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
  `controller`, `container` — which carry the controller fields only under the
  four-field aggregation above. Read them from `properties`, never from the response
  key: the key prefixes the controller with its kind (`deployment:immich-uqjcqc-server`)
  and `properties` does not. `namespaceLabels` also returns the owner, product and
  environment labels, which are useful for cross-checking but are **not** the source
  of attribution; the platform database is, because labels vanish with the namespace.
- Resolved controllers carry no pod-template hash — `immich-uqjcqc-server`,
  `bookstack-8d56q1-mysql` — because OpenCost collapses ReplicaSet to Deployment
  itself via `kube_replicaset_owner`. Reading `kube_pod_owner` directly would instead
  yield the ReplicaSet name, whose hash changes on every rollout and would fragment a
  subject per release.
- `running_seconds` is what distinguishes a quiet hour from a short one: a container
  that lived 11 of 60 minutes reports `minutes: 11.43584`, and
  `cpuCoreHours = cpuCores x minutes/60`.
- `pv_byte_hours` carries `role = allocation` because it is requested capacity, not
  consumption — PVC usage is not available from OpenCost. It is recorded because it
  arrives free in the same response. Volumes not mounted by a running pod arrive as a
  synthetic allocation whose `container` is `__unmounted__` — and under the four-field
  aggregation it **does** carry the tenant's namespace, so it is not self-excluding.
  The sampler skips it on `container == "__unmounted__"`, leaving orphaned PVCs
  unbilled: undercharging, never over, and storage is a non-goal of this change.
- No cost field is consumed. `cpuCost`, `ramCost`, `totalCost` and the idle and
  adjustment fields are deliberately ignored.

## Risks / Trade-offs

- **An OpenCost outage silently degrades the billable quantity to the request.** Its
  exporter loop stops, so the allocation series is absent for those minutes and a later
  replay falls back to the request — no error, no obvious symptom. → Both components are
  recorded, so a window can be audited after the fact by comparing the billable value
  against the higher of usage and request; undercharging, never over.
- **This failure has already happened once, and its window is unrecoverable.** Prometheus
  only began scraping OpenCost's own series at 2026-09-23T08:56:33Z. Every hour before
  that reports `cpuCoreHours` equal to the request for all 118 entries, bills zero CPU
  for 12 containers with measured usage, and resolves no controller for 111 workloads.
  Restarting OpenCost and discarding its ETL store changes nothing, because the inputs
  do not exist for that time. Both rules above were derived from measuring it.
- **A Prometheus outage is unrecoverable after ten days, and nothing yet reports that
  the sampler has stalled.** Monitoring is deliberately deferred: this change has grown
  well past its estimate and the sampler is being watched by hand for its first days
  instead. Until something reports lag, a silent stall loses history permanently once
  it passes retention. → Raising Prometheus retention as a recovery buffer is cheap and
  is a separate decision from where the record of truth lives.
- **OpenCost semantics can change across versions without the API changing.** → The
  chart version is pinned; a provenance table is the fuller answer and is deferred.
- **Request floors are no longer nominal, and the billable quantity is now dominated
  by them.** This was true when written; #132 gave every product container a request on
  2026-09-23. Measured over 15:00-17:00 that day, billable CPU core-hours exceed
  consumed ones by 4.6x for platform namespaces, 8.8x for one owner and 2.6x for
  another. Anything reasoning about what a bill would look like has to start from the
  request, not from usage.
- **Both environments record shared platform namespaces**, double-counting overhead if
  the two ledgers are ever summed together. Tenant namespaces no longer double-count —
  see the decision above — but platform ones have no owner to filter on. → Accepted:
  dev is never billed, and dev
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
- The bounded lookback for a first run is settled (six hours). The lag threshold at
  which the sampler is reported as behind is deferred with the rest of monitoring.
