## Why

A deployment's object storage bucket occupies real disk on its environment's Garage
instance, but none of it reaches the usage ledger. Garage publishes no per-bucket
metrics. The only size source is its admin API, one bucket per call, and every call
costs about 45 ms of Garage CPU for token verification. So the measurement has to be
built, and it has to scale to tens of thousands of mostly idle buckets on a single,
1-CPU Garage node. Tenant databases were metered on 2026-10-06 in a shape meant to take
object storage next.

**Depends on `daemons-image`.** The exporter introduced here is a Go daemon in the
shared `daemons` image.

## What Changes

- **A bucket size exporter** (`daemons/bucket-exporter/`), one per environment, beside
  its Garage instance:
  - It learns the bucket list from Garage and reads each `dep-*` bucket's size one call
    at a time, at a fixed, configurable rate starting at 0.2 calls/s.
  - It alternates between the bucket with recent writes read longest ago and the bucket
    read longest ago overall. Busy buckets stay fresh, and every bucket is re-read at
    least once per `2 × buckets ÷ rate`.
  - "Recent writes" comes from Garage's own request log in Loki. If that signal fails,
    the exporter falls back to reading buckets in plain order, at the same Garage load.
  - It publishes each bucket's size to Prometheus, which becomes the history the usage
    worker reads from.
- **A third usage source.** The usage worker reads each bucket's average size per
  closed window from Prometheus and records it as byte-hours against a new `bucket`
  subject. The deployment is taken from the bucket's name, `dep-<deployment id>`, and
  checked against the platform's records by primary key. Buckets of deleted deployments
  stop accruing at deletion, and buckets averaging zero bytes are not recorded.
- **A new catalogued quantity, `object_storage_byte_hours`,** priced at €0.02 per
  GiB-month (€0.0000274 per GiB-hour) from 2026-10-07. That's market-based: between
  Cloudflare R2 ($0.015) and AWS S3 Frankfurt ($0.0245). The plan's storage allowance
  is not recorded beside it.
- **The UI's "By resource" breakdown shows "Object storage"** alongside CPU, Memory and
  Database.
- **Each source's resume position becomes one index lookup.** Today it walks backwards
  through every newer sample of the other sources: on prod a source with no samples yet
  reads all 503k rows (0.9 s) every pass. Instead, a position is the newest window of
  the metrics only that source writes, served by a new index on
  `usage_sample (metric_id, window_start)`. This applies to the existing container and
  database sources too.
- **Garage provisioning mints one more scoped, non-expiring admin token per instance,**
  limited to `ListBuckets` and `GetBucketInfo`, for the exporter.

## Capabilities

### New Capabilities
- `bucket-size-exporter`: how each environment's bucket sizes are read from Garage and
  published. Covers which buckets, which reading goes next, at what rate, the activity
  signal and its fallback, restart behavior, and the exporter's credentials.
- `object-storage-usage`: how a bucket's size becomes ledger samples. Covers which
  buckets, over which windows, attributed to whom, when they stop accruing, and how the
  usage is priced and shown.

### Modified Capabilities
- `usage-sampler-worker`: a source's resume position is derived from the samples of
  the metrics only that source records, rather than of its subjects.
- `usage-ledger-data-model`: a subject may be a bucket, attributed through its name;
  object storage records consumption without an allowance.
- `garage-bucket-provisioning`: each instance provisions a second scoped admin token,
  for the bucket size exporter.

## Impact

- **New code:** `daemons/bucket-exporter/` (Go);
  `api/app/services/usage/buckets.py` (source).
- **Changed code:**
  - `api/app/services/usage/sampler.py`: per-source position, default sources.
  - `api/app/config.py`: one setting.
  - The `usage_sample` model gains an index.
  - `ui/src/components/usage/usageBreakdowns.ts`: one label.
- **Migration:** catalog row and rate; the new index on `usage_sample`.
- **Terraform:**
  - `tf/app/garage/`: exporter Deployment and Service, a second token in
    `scripts/provision.sh`, an image variable pinned to a `daemons` version.
  - `tf/app/caelus`: the usage worker's namespace setting.
- **Load:** about 9% of a Garage core at 2 calls/s, and about 1% at the initial
  0.2 calls/s. One Loki query every few minutes. One series per non-empty bucket in
  Prometheus. One hourly ledger row per non-empty bucket.
- **Docs:** `AGENTS.md`'s usage paragraph, and `ui/docs` where storage usage is
  described.
- **Out of scope:**
  - unfinished multipart uploads;
  - requests and egress;
  - PVC storage pricing;
  - daily windows;
  - a per-source `recorded_through`.
  - Upstream Garage changes are briefed in `var/garage/upstream-bucket-stats.md`.
