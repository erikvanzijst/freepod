## 1. Catalog and rate

- [x] 1.1 Write a migration, chained onto the current head, that inserts `db_byte_hours` and `db_allowance_byte_hours` (design D6) and a `usage_rate` row for `db_byte_hours` (0.000171 per 2^30, effective 2026-10-06); the downgrade removes all three. Verify with a migration test modeled on `tests/test_migration_usage_rate.py` covering the rows, the rate's metric, and the downgrade round trip, and that `tests/test_schema_drift.py` passes
- [x] 1.2 Add `usage_tenant_db_namespace` to `CaelusSettings`, empty by default (design D7); verify with a settings test that it reads `CAELUS_USAGE_TENANT_DB_NAMESPACE`

## 2. Sampler runs sources independently

- [x] 2.1 Make `last_recorded_window` take a subject kind; verify the existing test (a `build` sample does not advance the position) still passes with `container`, and add one where a `database` sample in a newer window does not advance the `container` position, and the reverse
- [x] 2.2 Extract the OpenCost-specific reading from `record_window` behind the source shape in design D3 (subject kind plus `read(window) -> rows | None`), leaving its behavior unchanged; verify the whole of `tests/test_usage_sampler.py` and `tests/test_usage_worker.py` passes unmodified
- [x] 2.3 Run `sample_once` once per source, each from its own position, stopping at its own first unusable window and isolating exceptions per source; verify with tests that an unusable database window leaves container windows recorded in the same pass, an OpenCost outage leaves database windows recorded, and a raising source does not stop the other

## 3. Database size source

- [x] 3.1 Add a Prometheus query helper for instant-vector queries at a given time (design D2), sharing transport and error handling with `OpenCostClient.allocation_series_cover`; verify with tests against a stubbed `httpx` client for a result, an empty result, a non-200 and an unreachable host
- [x] 3.2 Implement the trust check: `count(count_over_time(pg_database_size_bytes{namespace=<ns>}[w]))` at the window end, unusable when empty; verify with tests that an empty result makes the window unusable, and that the query carries the configured namespace
- [x] 3.3 Implement the value read: `avg_over_time(...{namespace=<ns>}[w])` at the window end, with no `datname` matcher (design D2), converted to byte-hours as an exact decimal; verify with tests for a full window, a partly covered window, a database present for only part of the window, and that the server's own databases in the result are not recorded
- [x] 3.4 Attribute from `deployment_database` joined to `deployment` by `db_name`: skip names it does not know, skip databases whose deployment's `deleted_at` is earlier than the window's end (design D5), and upsert `database` subjects with the tenant cluster's namespace; verify with tests for an unknown database, a deployment deleted mid-window and one deleted after the window, a catch-up replay spanning the deletion, and attribution surviving the deployment's deletion
- [x] 3.5 Emit `db_allowance_byte_hours` from the plan's `database_bytes`, skipping the row (not the window) when the plan declares none; verify with tests for a plan with an allowance and one without
- [x] 3.6 Register the source in the worker only when `usage_tenant_db_namespace` is set, logging once when it is not; verify with worker tests for both cases
- [x] 3.7 Keep `pg_database_size_bytes` as a single constant naming `tf/app/caelus/tenant-db.tf` as its other end, and select no databases by name prefix (design D2); verify by reading the module and with a test that the value query carries no `datname` matcher

## 4. Reporting and UI

- [x] 4.1 Verify in `tests/test_usage_report.py` that a `database` subject's `db_byte_hours` is reported under its deployment, owner and product, priced at the new rate (1 GiB for 730 h → 0.12483), that `db_allowance_byte_hours` never appears, and that a deleted deployment's history remains
- [x] 4.2 Add `db_byte_hours: 'Database'` to `METRIC_LABELS` in `ui/src/components/usage/usageBreakdowns.ts`; verify with a test that By resource labels it "Database" and ranks it third, and that `npm run lint`, `npm run build` and the UI test suite pass

## 5. Configuration and documentation

- [x] 5.1 Set `CAELUS_USAGE_TENANT_DB_NAMESPACE = var.namespace` in `tf/app/caelus/configmap.tf`; verify with `terraform validate`, and that a plan on the `default` (dev) workspace shows only the ConfigMap key and the checksum-driven restarts
- [x] 5.2 Update the usage bullet in AGENTS.md: the usage worker records from OpenCost and, for tenant databases, from Prometheus directly, and link the new spec; verify by reading it back

## 6. Rollout verification

- [x] 6.1 Run the full API test suite and the UI tests, and verify they pass
- [x] 6.2 On dev, after rollout and the next settled window: verify each live `deployment_database` row has a `database` subject attributed to its deployment, `db_byte_hours` / 2^30 matches the Prometheus `avg_over_time` for that window, an allowance sample is present, container windows kept advancing, and Settings → Usage → By resource shows Database
- [x] 6.3 Repeat 6.2 on prod

## 7. Scale

- [x] 7.1 Move `OpenCostSource` into `app/services/usage/containers.py`, beside `databases.py`; verify the sampler, worker and database tests pass unchanged apart from imports
- [x] 7.2 Make `Source.read` return observations lazily (`Iterable[Observation] | None`, `None` decided eagerly) and write them through `ledger.record_observations`, which chunks subjects into one multi-row upsert and samples into multi-row inserts of at most 1000; verify with `tests/test_usage_batching.py` counting statements per chunk and showing a source's generator is drawn only a chunk ahead of the writes
- [x] 7.3 Replace `resolve_subjects` and per-database `upsert_subject` calls with `subjects.upsert_subjects`, merging duplicates within a chunk; verify `tests/test_usage_subjects.py` passes through the new path and a duplicate keeps its deployment
- [x] 7.4 Attribute database sizes with one set-based join per chunk (design D4) and add a unique index on `deployment_database.db_name` (migration `5c8f3d0e2b47`, after checking both environments hold no duplicates); verify with a statement-count test showing three joins for five measured names in chunks of two and no subscription or plan reads, and a migration test for the index
