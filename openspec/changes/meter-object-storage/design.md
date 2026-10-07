## Context

See `proposal.md` for the motivation and the specs for the requirements. Facts that
shape the approach, measured 2026-10-07:

- **Garage offers one size source: `GetBucketInfo`, one bucket per call.** It returns
  `bytes`, `objects` and `unfinishedMultipartUpload*`. `/metrics` has no bucket label,
  and `GetClusterStatistics` gives totals only, and only below 1000 buckets. That holds
  in v2.3.0 (deployed) and v2.4.1 (latest). Internally the size counters are partitioned
  by bucket id, so even Garage reads them one bucket at a time.
- **Each authenticated admin call costs about 45 ms of Garage CPU.**
  `verify_authorization` runs Argon2 on every request. In-cluster, over one kept-alive
  connection:

  | Call | Time |
  |---|---|
  | `GetBucketInfo` | 45.3 ms |
  | `ListBuckets` | 44.8 ms |
  | `/check` (no auth, same lookups) | 0.47 ms |

  Concurrency doesn't help: Garage's 1-CPU limit caps it at about 20 calls/s.
- **Garage logs every request**, before handling it, as
  `<source> (key GK…) <METHOD> /<bucket>/<key>`. Buckets are always the first path
  segment, because `root_domain` is unset. Loki already ingests both Garage namespaces
  (retention 336 h; lines up to 168 h late are accepted).
  `sum by (bucket) (count_over_time(… | regexp … [24h]))` over prod's writes answered
  in 70 ms.
- **The bucket's alias is `dep-<deployment id>`,** the deployment's primary key
  (`deployment-object-storage`). Garage's own bucket id is random hex. All 15 prod and 3
  dev buckets map to live deployments in their own environment. Deployments are only
  ever soft-deleted (114 of 139 on prod). Teardown never deletes a bucket: it revokes
  the key and adds an expiry rule, and the drained bucket stays.
- **`usage_subject.deployment_id` has a foreign key to `deployment`.** A subject naming
  an unknown deployment fails the insert and rolls back the window.
- **A source's resume position scans when it lags.** `last_recorded_window(kind)`
  walks `ix_usage_sample_window` backwards, joining every row to its subject until one
  of the right kind turns up. On prod (503k samples) a source one hour behind reads
  2,980 rows. A kind with no samples reads all 503k (0.9 s), every pass.
- **The ledger grows about 123 bytes per sample** (62 MB for 505k rows, indexes
  included).
- **No per-environment setting exists yet** for where the exporter's series come
  from. `prometheus_base_url` and `loki_base_url` are already `tf/app` variables.

## Goals / Non-Goals

**Goals:**
- Garage load set by one rate setting, independent of bucket count.
- No per-bucket database round trip, in the exporter or the usage worker.
- The usage source has the same shape as the database source, so the sampler's window,
  gap and failure handling apply unchanged.

**Non-Goals:**
- Unfinished multipart bytes. Garage doesn't count them against the quota either
  (`UploadPart` never checks it); that's a separate problem.
- Requests and egress.
- Daily windows. Hourly rows for idle buckets are accepted until growth says otherwise.
- A per-source `recorded_through`. The label stays ledger-wide, and its occasional
  overstatement is accepted, because the Usage page is not an invoice.
- Removing the per-bucket read loop. That waits for Garage upstream; see
  `var/garage/upstream-bucket-stats.md`.

## Decisions

### D1: A Go exporter beside Garage, publishing to Prometheus

A `bucket-exporter` daemon in the shared `daemons` image (`daemons-image`). It runs as
one Deployment per environment in `tf/app/garage/`, in the Garage namespace. It reaches
the admin API over the namespace's headless Service and is scraped through an annotated
Service, like the tenant database exporter.

It is Go rather than a `caelus` worker because a Python worker on the API image costs
120–220 MiB per environment and a Go daemon 5–12 MiB. It shares nothing with the API.

*Alternative considered:* the usage worker calls Garage itself at window close.
Rejected for the reason D1 of `meter-relational-storage` rejected the same idea for
databases: no history. Any usage worker outage would be a permanent gap, where
Prometheus keeps 10 days to replay from.

*Alternative considered:* the `garage` CLI, or a Rust client over Garage's RPC. Both
skip the Argon2 check, but both need `rpc_secret`, which is full control of the
cluster. The RPC client would also have to be rebuilt for each Garage version. Rejected.

### D2: Reading order, rate and state

The exporter's state is in memory. Per bucket: `bytes`, `read_at`, `written_at`, keyed
by alias. Garage id → alias comes from the bucket list.

Two independent loops:

- **Refresh, every `refresh_interval` (default 5 min):**
  - `ListBuckets`: adds new `dep-*` aliases with `read_at = 0` and drops vanished ones.
  - The Loki activity query (D3): sets `written_at`.
  - Garage's `/metrics` (D4).
- **Read, at `rate` calls/s (default 0.2):** on alternating turns,
  - the bucket with `written_at > read_at` and the smallest `read_at`;
  - the bucket with the smallest `read_at` overall.

  The first turn falls through to the second when no bucket is changed. A read sets
  `bytes` and `read_at = now`. A min-heap or a sorted scan is fine at 50k buckets.

The rate setting's comment carries the spec's table. Worst case is
`2 × buckets ÷ rate`; on a quiet platform it's half that.

| Rate | 50k buckets, worst case | 50k buckets, quiet |
|---|---|---|
| 0.2 Hz | 5.8 days | 2.9 days |
| 1 Hz | 28 h | 14 h |
| 5 Hz | 5.6 h | 2.8 h |

*Alternative considered:* separate budget shares for changed and idle buckets, with
unused share flowing over. Alternating gives the same guarantee with nothing to tune.

### D3: The activity signal is a Loki query over Garage's request log

```
sum by (bucket) (count_over_time(
  {namespace="<garage ns>", container="garage"} |~ ` (PUT|POST|DELETE) /`
  | regexp `[\])0-9] (?:PUT|POST|DELETE) /(?P<bucket>[^/?\s]+)`
  | bucket != "" | bucket != "v2"
  [<to − from>s]))
```

- It's an instant query evaluated at `to`, returning one series per bucket written to in
  the range. The count is a side effect: LogQL has no "exists" for log lines, and a
  plain log query would return every matching line instead.
- The line filter runs before the regular expression, so it only extracts from write
  lines, and the `bucket != ""` filter keeps unmatched lines out of the result, which
  would otherwise form one series with an empty `bucket`.
- No `(key GK…)` filter: browser form uploads (`PostObject`) authenticate in the body
  and are logged without a key, e.g. `<ip> (via <proxy>) POST /artifacts`. The method
  is matched after any source form instead. Admin API requests share the log and are
  addressed to `/v2/…`; `v2` is too short to be a bucket name, so it is dropped.
- `container="garage"` keeps the namespace's other pods (the provisioning Job, the
  exporter itself) out of the stream.
- `from` is the cursor and `to` is `now − lag`, with a lag of 1 min for ingestion delay.
  The cursor advances to `to` only on success, so a Loki outage is re-read later,
  within Loki's 14 days. After a long outage the range is capped, for example at 1 h
  per query, and catches up over several refreshes.
- A `bucket` that isn't a known alias is looked up as a Garage id, then ignored.
- Anyone can send a request naming any bucket. By D2's construction that only reorders
  reads.
- The log line is not a Garage interface. A test pins the regular expression against
  sample lines from v2.3.0, and D4 catches a format change in production.

*Alternative considered:* Traefik access logs. Rejected: they miss in-cluster requests,
and nothing forces tenants through the public endpoint.

*Alternative considered:* a proxy in Garage's data path. Rejected: it adds latency and
a point of failure to every S3 request.

### D4: Cross-checking the signal with Garage's own counter

Each refresh, the exporter reads Garage's `/metrics` directly; it's already on the
admin port and unauthenticated by default. It sums `api_s3_request_counter` over the
writing endpoints:
`PutObject`, `PostObject`, `CopyObject`, `UploadPart`, `UploadPartCopy`,
`CompleteMultipartUpload`, `AbortMultipartUpload`, `DeleteObject`, `DeleteObjects`.

If that sum grew since the last refresh but Loki returned no lines, the signal is
broken. A decrease in the sum is a Garage restart, and is skipped. Then:

- `caelus_bucket_exporter_activity_signal_ok` is set to 0, and a warning is logged.
- `written_at` is left untouched, so reads fall through to plain order (D2).

The check is deliberately only "some versus none". Counters and log lines don't line
up exactly at interval edges.

The counter is read at each refresh, but the log only up to `now − lag`, so a write in
the final lag of an interval is counted before the log shows it. The check therefore
judges the latest interval between two counter readings that the log has been read past
(the previous one, given `refresh_interval ≥ lag`), against the log windows that overlap
it. An interval with no counted writes, a restart, or one the stored windows don't
cover keeps the last verdict; Loki failing sets the signal to 0 until it answers.

Prometheus doesn't scrape Garage today, and this doesn't need it to.

### D5: What the exporter publishes

| Series | Meaning |
|---|---|
| `caelus_bucket_bytes{bucket}` | completed-object bytes at the last read; published for every known bucket, including zeros |
| `caelus_bucket_exporter_buckets` | number of known buckets; always published, including 0 |
| `caelus_bucket_exporter_last_success_timestamp_seconds` | last successful Garage call |
| `caelus_bucket_exporter_read_errors_total` | failed size reads |
| `caelus_bucket_exporter_activity_signal_ok` | 1 or 0 (D4) |

- **Zeros are published.** The usage source averages over the window, so a bucket
  emptied mid-window must contribute its zeros. Skipping empty buckets happens in the
  source, after averaging (spec: *A bucket emptied mid-window*).
- **The liveness series is `buckets`,** not any bucket series. An environment with no
  buckets must still have usable windows.
- **Old sizes are never dropped.** While Garage is down, nothing can change sizes. When
  reads fail but writes continue, the cost is staleness, which the error counter and
  timestamp make visible. The alternative, unpublishing, would make whole windows
  unusable, and the sampler can never get past a window that was never measured.
- **Restart:** the exporter queries
  `last_over_time(caelus_bucket_bytes{namespace=…}[10d])` from Prometheus at startup
  and seeds those aliases with `read_at = 0`. Each past pod published under its own
  `instance`, so a bucket can have several series; the one kept is from the pod whose
  `last_success_timestamp_seconds` is latest.

### D6: The usage source

`BucketSizeSource` in `api/app/services/usage/buckets.py`, shaped like
`DatabaseSizeSource`:

- **Liveness:**
  `count(count_over_time(caelus_bucket_exporter_buckets{namespace="<ns>"}[<w>s]))`.
- **Values:** each bucket's average over all its samples in the window,
  `sum by (bucket) (sum_over_time(caelus_bucket_bytes{namespace="<ns>"}[<w>s]))`
  divided by the same `count_over_time`. Not a plain `avg_over_time`: each scrape
  carries the exporter pod's `instance`, so a restart mid-window splits a bucket into
  two series. Buckets averaging 0 are dropped, along with names that don't parse as
  `dep-<uuid>`.
- **Confirmation:** one statement per chunk of 1000.

  ```sql
  SELECT u.bucket, u.deployment_id, u.size_bytes
  FROM unnest(CAST(:buckets AS text[]), CAST(:ids AS uuid[]),
              CAST(:sizes AS numeric[])) AS u(bucket, deployment_id, size_bytes)
  JOIN deployment d ON d.id = u.deployment_id
  WHERE d.deleted_at IS NULL OR d.deleted_at >= :window_end
  ```

  This is a primary-key join with no subscription or plan joins. It is the deletion
  cutoff and the foreign-key guard in one. It is not a scalability concern: per chunk,
  the ledger itself already runs a subject upsert and a sample insert.
- **Subject:** `kind=bucket`, `ref` = the alias, `namespace` = the Garage namespace,
  `deployment_id` from the name.
- **One setting:** `usage_bucket_namespace` (`CAELUS_USAGE_BUCKET_NAMESPACE`), set to
  the Garage namespace by `tf/app`. Empty disables the source, as with databases.

*Alternative considered:* no lookup at all, with deployment ids taken straight from the
names. Rejected.
- A deleted deployment's bucket would be billed until drained, then recorded as zero
  forever.
- An unknown id would fail the foreign key and stall the source at that window.

Moving deletion into the exporter, by treating a keyless bucket as deleted, would only
take effect at the bucket's next read, which can be days away at 0.2 Hz.

### D7: Resume positions from source-exclusive metrics

Each source declares the metrics only it writes, and its position is the newest
`window_start` among them. Each lookup is
`SELECT max(window_start) FROM usage_sample WHERE metric_id = :m`, served backward from
the new index `ix_usage_sample_metric_window (metric_id, window_start)`.

| Source | Position metrics |
|---|---|
| containers | `network_receive_bytes`, `network_transmit_bytes`, `pv_byte_hours` |
| databases | `db_byte_hours` |
| buckets | `object_storage_byte_hours` |

Builds write every other container metric, which is why those three are the
containers' only safe choice. A test asserts that the sources' sets are disjoint and
that none intersects what `builds.window_quantities` produces.

Verified on a local Postgres with 5.3M synthetic rows, all index-only:

| Case | Time |
|---|---|
| Source 200 h behind | 0.045 ms |
| Source with no samples | 0.011 ms |
| Three-metric union | 0.024 ms |

The new index is about the size of `ix_usage_sample_window` (5.5 MB on prod today).

*Alternative considered:* a progress table written in each window's transaction.
Rejected: it's another moving part, for a lookup an index serves.

*Alternative considered:* denormalizing `kind` onto `usage_sample`. Rejected: it adds a
column to every row of the largest table.

### D8: Ledger, rate and UI

One migration:
- adds the catalog row `object_storage_byte_hours` (storage, byte_hours, delta, usage);
- adds its rate, `0.0000274` per 2³⁰ from 2026-10-07;
- creates the index, inside the migration's transaction. `CONCURRENTLY` would need
  an autocommit block, which commits the transaction that holds the runner's advisory
  lock (`alembic/env.py`). A plain build of prod's 505k rows takes well under a second,
  blocking only the usage worker's inserts meanwhile.

The rate is €0.02 / 730 h = €0.0000273973/GiB-h, rounded to €0.0000274: €0.020002 per
GiB-month. It's market-based, like the database rate (`meter-relational-storage` D6):

| Provider (standard tier, per GB-month) | Price |
|---|---|
| AWS S3 Frankfurt | $0.0245 |
| GCS europe-west3 | $0.023 |
| Azure Hot LRS West Europe | $0.0196 |
| DigitalOcean Spaces overage | $0.02 |
| Scaleway Multi-AZ | €0.01606 |
| Cloudflare R2 | $0.015 |
| Hetzner | ~€0.0087 |
| Backblaze B2 | $0.00695 |

Note that the OpenCost cost model prices local disk at about €0.057/GiB-month, so this
rate is below the platform's own modeled disk cost. That's accepted while nothing is
billed.

`METRIC_LABELS` gains `object_storage_byte_hours: 'Object storage'` after Database,
which fixes its palette slot.

### D9: Garage provisioning

`tf/app/garage/scripts/provision.sh` mints a second non-expiring token,
`bucket-exporter`, scoped to `ListBuckets` and `GetBucketInfo`. It follows the same
keep-if-held, replace-if-lost logic as the API token. The token is written under a new
key in the existing keys Secret, which the exporter's Deployment reads by
`secretKeyRef` in the same namespace. Terraform never sees it.

## Risks / Trade-offs

- **[Idle buckets can be days stale at 0.2 Hz]** At 50k buckets, an idle bucket shrunk
  by a tenant-set lifecycle rule is billed at its old size for up to 5.8 days. → Chosen
  deliberately for weak hardware. Raise the rate, or land an upstream bulk endpoint.
- **[The activity signal parses a log line]** → D4 detects breakage and degrades to
  plain order; a test pins the format.
- **[A whole window without the exporter stalls the source]** The sampler never passes
  an unmeasured window. This is the existing behavior for databases too. → The
  exporter's restart is seconds, and partial windows are recorded. A longer outage needs
  the same operator attention a database exporter outage does today.
- **[Garage CPU]** 0.2 Hz is about 1% of a core, and 2 Hz about 9%. → Bounded by the
  rate (spec), whatever the bucket count.
- **[Containers' position rests on three OpenCost fields]** If OpenCost stopped
  reporting all three, the container source would never see its position advance. It
  would re-record the same windows, which is harmless thanks to `DO NOTHING`, and never
  move on. → All three have appeared in every container sample so far (41,979 each on
  prod). The test in D7 keeps builds from ever writing them.
- **[Hourly rows for every non-empty bucket]** About 123 bytes per row, so about 1 GB a
  year per 1,000 non-empty buckets. → Accepted. Daily windows are the lever when growth
  calls for them.

## Migration Plan

Prerequisite: `daemons-image` is applied and `daemons` is published.

1. Merge, with `daemons/VERSION` bumped. CI publishes the new `daemons` version.
2. Migration: catalog row, rate, index. Purely additive. The new position
   lookup ships in the same image as the index.
3. `terraform apply` on dev:
   - provisioning mints the exporter token;
   - the exporter Deployment and Service come up;
   - `CAELUS_USAGE_BUCKET_NAMESPACE` is set;
   - roll the usage worker (`scripts/rollout.sh`).
4. Verify on dev:
   - `caelus_bucket_exporter_buckets` and `caelus_bucket_bytes` appear in Prometheus;
   - a write to a dev bucket gets a read within a minute;
   - after the next settled window, every non-empty bucket of a live deployment has an
     `object_storage_byte_hours` sample matching the Prometheus average;
   - Settings → Usage shows Object storage.
5. Repeat on prod.

**Rollback:**
- Unset `CAELUS_USAGE_BUCKET_NAMESPACE` to disable the source without a deploy.
- Scale the exporter to zero.
- Samples already written stay valid.
- The index and the new position lookup can stay. They're independent of buckets.
