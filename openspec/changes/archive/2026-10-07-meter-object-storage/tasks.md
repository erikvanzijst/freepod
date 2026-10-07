## 1. Resume positions from source-exclusive metrics (D7)

- [x] 1.1 Add `ix_usage_sample_metric_window (metric_id, window_start)` to the `usage_sample` model, with a migration that creates it inside the migration's transaction (a plain build: sub-second at prod's size, and `CONCURRENTLY` would release the runner's advisory lock); verify `alembic upgrade head` and `downgrade -1` on the test database, and `EXPLAIN` of `max(window_start) WHERE metric_id = …` uses an index-only backward scan
- [x] 1.2 Give each sampler source its position metrics (containers: `network_receive_bytes`, `network_transmit_bytes`, `pv_byte_hours`; databases: `db_byte_hours`) and derive `last_recorded_window` from them, one index lookup per metric; verify the existing sampler tests pass, including "another writer's samples do not advance the sampler"
- [x] 1.3 Add a test that the sources' position metrics are pairwise disjoint and that none is among the quantities `builds.window_quantities` produces; verify it fails when a build quantity is added to a position set
- [x] 1.4 Add a test that a source with no samples finds its position without reading other sources' samples (e.g. assert the query plan or a statement count against a ledger seeded with other kinds); verify it passes

## 2. Ledger catalog, rate and UI (D8)

- [x] 2.1 Migration: catalog row `object_storage_byte_hours` (storage, byte_hours, delta, usage) and rate `0.0000274` per `2^30` from 2026-10-07, with a downgrade that removes them; verify upgrade/downgrade on the test database and that a 1 GiB × 730 h report row costs €0.020002
- [x] 2.2 Add `object_storage_byte_hours: 'Object storage'` to `METRIC_LABELS` after `db_byte_hours`; verify `npm test` in `ui/` passes and the label renders in the "By resource" breakdown

## 3. Usage source (D6)

- [x] 3.1 Add `usage_bucket_namespace` (`CAELUS_USAGE_BUCKET_NAMESPACE`) to settings; an empty value disables the source and is logged once at startup; verify with a settings test
- [x] 3.2 Implement `BucketSizeSource` in `api/app/services/usage/buckets.py`: liveness on `caelus_bucket_exporter_buckets`, values from each bucket's average over `caelus_bucket_bytes…` across series (D6), drop zero averages and names that aren't `dep-<uuid>`, and the chunked primary-key join with the `deleted_at` cutoff; position metric `object_storage_byte_hours`. Verify unit tests covering:
  - constant size;
  - an empty bucket not recorded;
  - a bucket emptied mid-window recorded at half;
  - exporter absent for the whole window means unusable, with no samples and no progress;
  - liveness present with no buckets means a usable, empty window;
  - another namespace's series ignored;
  - an unknown deployment id dropped while the others are recorded;
  - a deleted deployment cut off at deletion, including on late catch-up;
  - a malformed name dropped.
- [x] 3.3 Register the source in `default_sources` when the namespace is set; verify a sampler test where the bucket source stalls while containers and databases keep recording
- [x] 3.4 Verify the bucket statement count per window is `ceil(N/1000)` joins plus the ledger's own chunked writes, with a test over more than one chunk of buckets

## 4. Bucket size exporter (`daemons/bucket-exporter/`)

- [x] 4.1 Create the Go module with configuration from the environment: admin URL, token, Garage namespace, Loki URL, Prometheus URL, rate (default 0.2, its comment carrying the 0.2/1/5 Hz table), refresh interval (default 5 min), Loki lag, and listen address. Verify `GOWORK=off go vet ./...` and a config test
- [x] 4.2 Garage client: `ListBuckets`, `GetBucketInfo`, `/metrics` parsing of the writing endpoints' `api_s3_request_counter`; verify tests against recorded v2.3.0 responses
- [x] 4.3 State and reading order (D2): bucket list refresh (add `dep-*` with `read_at=0`, drop vanished, map Garage id → alias), alternating choice with fall-through, one read per tick at the configured rate. Verify tests for:
  - alternation;
  - the fall-through when nothing has changed;
  - many writes needing one read;
  - the starvation bound `2N/rate` under constant activity;
  - the platform bucket ignored.
- [x] 4.4 Activity signal (D3): the Loki query over `[cursor, now−lag)`, cursor advanced only on success, Garage-id paths mapped to aliases, unknown names ignored. Verify a test pinning the regular expression against sample v2.3.0 log lines, both the via-proxy form and the direct form, keyless form uploads included, and the cursor test for a failed query
- [x] 4.5 Cross-check (D4): the counter rose and Loki reported nothing → `activity_signal_ok=0` and changed-marking suspended; a counter decrease is treated as a restart. Verify tests for each case
- [x] 4.6 Publishing (D5): `caelus_bucket_bytes{bucket}` including zeros, `caelus_bucket_exporter_buckets`, last-success timestamp, read error counter, signal gauge; sizes kept when reads fail. Verify a test scraping the handler before and after a failed read
- [x] 4.7 Restart seed (D5): query `last_over_time(caelus_bucket_bytes{namespace=…}[10d])` at startup and seed with `read_at=0`; startup proceeds if Prometheus is unavailable. Verify tests for both cases
- [x] 4.8 Bump `daemons/VERSION`; verify `docker build daemons/` produces `/bucket-exporter` alongside the others and it starts with valid configuration against a local Garage or recorded responses

## 5. Garage provisioning and Terraform

- [x] 5.1 `tf/app/garage/scripts/provision.sh`: mint the `bucket-exporter` token scoped to `ListBuckets` and `GetBucketInfo`, non-expiring, keep-if-held / replace-if-lost, written under a new key in the keys Secret (D9). Verify by re-running the provisioning Job on dev: the token is unchanged, and using it for `CreateBucket` is refused
- [x] 5.2 `tf/app/garage/bucket-exporter.tf`: a Deployment (one replica, `command = ["/bucket-exporter"]`, image variable pinned to the new `daemons` version, token by `secretKeyRef`, small requests per the idle-floor rule) and a Service annotated for Prometheus scraping; wire `prometheus_base_url` and `loki_base_url` from `tf/app`. Verify `terraform plan` on dev adds only these resources and the Job change
- [x] 5.3 `tf/app/caelus/configmap.tf`: `CAELUS_USAGE_BUCKET_NAMESPACE` = the Garage namespace; verify the plan shows only that key added

## 6. Docs

- [x] 6.1 `AGENTS.md` usage paragraph: buckets as a third source via the exporter, with links to the two new specs and this design. `daemons/bucket-exporter/README.md`: a terse entry with how to run and test it, linking the specs. Verify the links resolve
- [x] 6.2 `ui/docs/apps/plans-and-billing.md` and `ui/docs/developers/usage-and-billing.md`: say Settings → Usage covers CPU, memory, databases and object storage (both currently say CPU and memory only). Verify `npm run build` in `ui/docs`

## 7. Roll out

- [x] 7.1 Dev:
  - `terraform apply` (`default` workspace) and roll the usage worker;
  - `caelus_bucket_exporter_buckets` and `caelus_bucket_bytes` appear in Prometheus for `caelus-garage-dev`;
  - a write to a dev bucket is followed by a read of it within a minute (exporter log);
  - `activity_signal_ok` is 1.
- [x] 7.2 After the next settled window on dev:
  - every non-empty bucket of a live deployment has an `object_storage_byte_hours` sample equal to the Prometheus average × hours;
  - Settings → Usage shows Object storage.
- [x] 7.3 Repeat 7.1–7.2 on `prod`
