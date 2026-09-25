## Context

See proposal.md for why. The facts this design rests on, established before writing it:

- **Build pods are invisible to the sampler at the resolution that matters.** Builds run
  41–127 s (median 65 s over 68 successful prod builds); cAdvisor is scraped every 60 s.
  Of prod's last two builds before this change, one got one CPU sample, so no rate, and
  the other got none.
- **The container can measure itself exactly.** Verified on dev with the real builder
  image (`builder:0.2.0`) as uid 1000: the container is its own cgroup v2 root
  (`0::/`), `cpu.stat`, `memory.current`, `memory.peak` and `memory.stat` are readable,
  and 2 s of busy loop in a *child* process added 1.92 s to `cpu.stat usage_usec` — so
  BuildKit's processes are counted. Node kernel is 6.8; `memory.peak` needs 5.19.
- **The builder already reports through a JSON termination message**, `{"image": …}` on
  success and `{"error": …}` on failure. The worker reads it only on success today.
- **The Job's `ttlSecondsAfterFinished` is 3600**: the report is gone an hour after the
  build ends.
- **The usage sampler resumes from the newest `window_start` in the whole ledger**
  (`sampler.last_recorded_window`).
- **Builds belong to a deployment** (`builds-belong-to-deployments`), and the usage
  report attributes every subject through `usage_subject.deployment_id`.

## Goals / Non-Goals

**Goals:**

- A build's measured usage reaches the ledger exactly once, from stored state only.
- Build usage appears in every existing report with no change to reporting.
- Build usage and sampled usage never double-count or disturb each other's progress.

**Non-Goals:**

- Backfilling builds that ran before this ships.
- A report dimension separating build usage from runtime usage. The subject kind makes
  it derivable later.
- Network and storage for builds.

## Decisions

### D1: The build measures itself, rather than being sampled faster

The builder reads its own cgroup: `cpu.stat usage_usec` once at exit, and a background
thread integrates working set — `memory.current` minus `inactive_file` from
`memory.stat`, the same working-set definition OpenCost uses — every 2 s into
byte-seconds. It also reads `memory.peak`, and records its own wall-clock start and end
in UTC.

*Alternative considered:* scrape cAdvisor every 15 s instead of 60 s. Rejected: the
interval is per scrape job, so every container on the node pays roughly four times the
Prometheus storage; builds under 15 s are still missed; and CPU is still rounded to
whole minutes by OpenCost. The workload this is for is the one sampling measures worst.

*Trust:* the report comes from a container running tenant code, but the tenant's build
steps run inside BuildKit's sandbox, not in the builder process, and cannot write its
termination message. The billable quantity is also floored at the request (D5), so a
report can only raise a build's bill above its floor, never lower it.

### D2: Usage rides in the existing termination message

```json
{"image": "5@sha256:…",
 "usage": {"cpu_seconds": 41.2, "memory_byte_seconds": 7.1e10,
           "memory_peak_bytes": 812000000,
           "started_at": "2026-09-25T22:45:41Z", "finished_at": "2026-09-25T22:46:56Z"}}
```

The same `usage` object accompanies `error` on failure. It is well under the 4 KiB
termination-message limit. The worker reads the message on failure as well as on
success.

### D3: Measurements are stored on the build row, when the worker sees it finish

New nullable columns on `build`: `usage_cpu_seconds`, `usage_memory_byte_seconds`,
`usage_memory_peak_bytes`, `usage_started_at`, `usage_finished_at`, `usage_measured`
(boolean) and `usage_recorded_at`. They are written in the same transaction that moves
the build to its terminal status, which is the last moment the report is certainly
readable.

*Alternative considered:* a JSON column holding the report. Rejected: the recording
pass does arithmetic on these values, and typed columns make a malformed report fail at
the write rather than an hour later in the pass.

### D4: A recording pass on every worker tick, keyed on a marker column

Each build worker pass selects:

```sql
WHERE status IN ('succeeded', 'failed') AND job_id IS NOT NULL
  AND usage_recorded_at IS NULL
  AND date_trunc('hour', coalesce(usage_finished_at, finished_at))
      + window + settle <= now()
```

For each build it computes the samples (D5), inserts them with the ledger's existing
`ON CONFLICT DO NOTHING` insert, and sets `usage_recorded_at`, in one transaction. A
restart, a crash mid-way or two racing passes all converge on exactly one set of
samples, because the work is a pure function of the row and the insert is idempotent.
`window` and `settle` are the usage sampler's own settings (`usage_window_seconds`,
`usage_settle_seconds`), so both writers agree on when a window may be written.

The query is bounded by the marker's partial index (`WHERE usage_recorded_at IS NULL`).

*Alternative considered:* recording each window as it closes, tracking progress per
build. Rejected: a build spans at most two windows, so waiting for the last costs at most
an hour and saves a second piece of state.

### D5: Quantities per window

With `f` the fraction of the run inside a window, `h` the hours of the run inside it, and
the build's request and limit from `build_jobs` (`500m` / `1Gi` request, `2` / `6Gi`
limit):

| Metric | Value for the window |
|---|---|
| `cpu_core_hours` | `max(request_cores × h, cpu_seconds × f / 3600)` |
| `ram_byte_hours` | `max(request_bytes × h, memory_byte_seconds × f / 3600)` |
| `cpu_usage_cores_avg` | `cpu_seconds / wall_seconds` |
| `ram_usage_bytes_avg` | `memory_byte_seconds / wall_seconds` |
| `cpu_request_cores_avg`, `cpu_limit_cores_avg` | the request or limit |
| `ram_request_bytes_avg`, `ram_limit_bytes_avg` | same |
| `running_seconds` | `h × 3600` |

Averages are over the build's run, not over the window. That is what OpenCost reports
for containers, and so what every container row in the ledger already means — verified
on 2026-09-25 against OpenCost's allocation API: the `catalog` init container ran 40 of
60 minutes with `ramByteUsageAverage` 94,392,320 and `ramByteHours` 62,928,213, which is
exactly the average × 40/60. The ledger is append-only, so its existing rows fix the
convention; build rows follow it rather than silently meaning something else.

Splitting a total by wall-clock share is exact for the sum and approximate only in how
it divides between two hours; nothing is billed per hour.

The floor matches OpenCost's `max(request, usage)`, applied here to window totals rather
than per minute. That undercounts a bursty build relative to OpenCost's per-minute max,
never overcounts, and is the best the totals can support.

### D6: Builds that finished before this change are never recorded

The migration that adds the columns sets `usage_recorded_at` on every build already in a
terminal status. The recording pass therefore never selects them, and no samples are
written for them: they are not billed. The marker, not the null usage columns, is the
signal, because a build killed after this ships also has null usage columns and must
still be recorded (D7).

### D7: Missing measurements are estimated from the build row

A build with a Job but no usage report records `request × h` for the billable metrics,
the request and limit averages and `running_seconds`, using the worker-observed
`started_at`/`finished_at`, and `usage_measured = false`. The usage-average metrics are
**not** recorded for it: the ledger distinguishes "not measured" from "zero", and nothing
was measured.

This covers OOM kills and deadline kills (no chance to report), builds from a builder
image predating this change, and a worker down longer than the Job's TTL.

### D8: A `build` subject kind, attributed from the build row

The subject is `kind = 'build'`, `ref = <build id>`, `namespace` = the builds namespace
it ran in, `deployment_id` = the build's deployment. `SubjectKind` gains `BUILD`; the
column is text, so no migration touches `usage_subject`. The report already joins
subjects to deployments, users and products, so build usage appears under its
application with no reporting change.

### D9: The sampler's progress ignores other writers, and skips its own builds

`last_recorded_window` becomes the newest `window_start` among samples of
`kind = 'container'` subjects. Without this, a build recorded for 14:00 while the
sampler was stalled behind 14:00 — for instance during an OpenCost outage — would move
the sampler's resume position past 14:00 and lose that hour for every container. The
closed-window rule of D4 does not prevent this; only scoping the position does.

The sampler also drops allocations in `settings.builds_namespace`. The other
environment's builds namespace stays platform overhead, exactly as every other shared
platform namespace is recorded by both environments today.

*Alternative considered:* a per-writer progress table. Rejected by the ledger's own
design, which derives progress from the ledger precisely to avoid a second source of
truth; filtering by subject kind keeps that property.

## Risks / Trade-offs

- **A build near an hour boundary reaches the ledger up to about an hour late.** → Usage
  views say what they are measured through; an hour's delay on a build is well inside
  what monthly billing needs.
- **Builds from the old builder image are recorded as estimated** until the new image is
  rolled out. → The builder rolls out in the same change; estimated builds are marked.
- **The resume query now joins subjects.** → It still walks the `window_start` index
  newest-first and stops at the first container sample, which is in the newest window
  whenever the sampler is keeping up.
- **The report comes from a container that ran tenant code.** → See D1: tenant code
  cannot reach the builder's termination message, and the request floor bounds any
  error downward.
- **Gauge amounts are overstated for anything that ran part of a window.** Pre-existing:
  `usage_amount` multiplies a run-average by the whole window. It affects the diagnostic
  usage and allowance amounts only, never the billed quantities, and builds inherit it by
  following the ledger's convention. See Open Questions.

## Migration Plan

1. Migration adds the `build` columns and the partial index, and marks every build
   already terminal as recorded, so none of them is ever billed.
2. Release the builder image (`VERSION` bump), and point `builder_image` at it.
3. Roll out the API and workers. Builds finishing from then on are recorded, and the
   sampler stops recording the builds namespace. A build running across the switch may
   already have been sampled as unattributed platform overhead for a window, and is then
   recorded again as build usage: at most the few builds in flight, counted twice only
   in totals that include overhead, which is never billed.

**Rollback:** roll back the workers; the columns can stay. Recorded build samples remain
valid ledger rows.

## Open Questions

- **Should `usage_amount` scale gauges by `running_seconds` rather than the window
  length?** That corrects every existing and future row at once without rewriting a
  sample, since the ledger already records `running_seconds` beside each gauge. It is a
  change to how the ledger is read, not to what this change writes, so it can follow as
  its own change.
