## 1. Data model

- [x] 1.1 Add `UsageMetricORM`, `UsageSubjectORM` and `UsageSampleORM` SQLModel
      definitions with the natural primary key on samples, and verify
      `test_schema_drift` reports no drift between models and migrations
- [x] 1.2 Write the Alembic migration creating the three tables, the
      `window_start` btree, the partial index on `usage_subject.deployment_id`,
      the `usage_subject.namespace` index and the `usage_amount` view, and verify
      it applies and reverses cleanly on a scratch database
- [x] 1.3 Seed the metric catalog rows in the same migration (CPU, memory and
      network quantities, both roles, plus runtime) and verify a sample cannot be
      written naming an uncatalogued quantity
- [x] 1.4 Add a service function that records a batch of samples idempotently, and
      verify with a test that replaying an already-recorded window leaves values
      unchanged and raises nothing

## 2. Measurement source

- [x] 2.1 Add an OpenCost client that fetches `/allocation` for a window at hourly
      granularity aggregated by namespace, controllerKind, controller and container,
      and verify against a recorded response fixture that it parses quantities,
      `minutes` and `properties`
- [x] 2.2 Map an allocation to catalogued quantities per the mapping table in
      `design.md`, and verify with a test that each expected
      metric is produced with the right kind and role
- [x] 2.3 Treat a non-200, an empty result set, or a window not covered by samples of
      OpenCost's own `container_cpu_allocation` series as "no data", and verify with a
      test that nothing is written and no progress is recorded for such a window
- [x] 2.4 Add the Prometheus presence check itself — one query asking whether
      `container_cpu_allocation` covers the window — and verify against recorded
      responses that a covered window passes and an uncovered one does not

## 3. Subject resolution

- [x] 3.1 Resolve a container subject reference from the allocation's properties
      as `<namespace>/<controllerKind>/<controller>/<container>`, skipping entries
      whose container is `__unmounted__`, and verify with a test that pod restarts
      map to one subject
- [x] 3.2 Resolve the owning deployment from the platform database by namespace,
      recording platform namespaces with no deployment, and verify with tests
      covering a tenant namespace, a platform namespace and an unknown namespace
- [x] 3.3 Backfill `deployment_id` on an existing subject when a previously
      unresolved namespace later resolves, and verify with a test that samples are
      untouched
- [x] 3.4 Record an entry whose controller is unresolved against
      `<namespace>/unresolved/unresolved/<container>` rather than skipping it, and
      verify with tests that it is attributed to the owning deployment, that it is
      distinguishable from a resolved subject, and that it does not block progress

## 4. Sampler loop

- [x] 4.1 Derive the resume position from the ledger, falling back to a bounded
      configurable lookback when it is empty, and verify with tests for an empty
      ledger, a current ledger and one that has fallen behind
- [x] 4.2 Compute the end of the recordable range as the last complete window after
      a settling allowance, and verify with a test that a run at 14:30 records
      13:00–14:00 as its latest window and writes no partial window
- [x] 4.3 Replay gaps at window granularity in bounded chunks, persisting progress
      per chunk, and verify with a test that a 24-hour gap produces 24 windows and
      that an interrupted catch-up resumes without duplicates
- [x] 4.4 Make the loop safe to run concurrently, and verify with a test that two
      simultaneous runs over the same window leave one sample per subject, quantity
      and window

## 5. Worker process and deployment

- [ ] 5.1 Add the `caelus usage-worker` command running the loop on its configured
      tick, and verify it starts against a local database and records a window
- [ ] 5.2 Add the worker Deployment to `tf/app/caelus`, reusing the API image and
      service account, and verify `terraform plan` shows only the new Deployment
- [ ] 5.3 Add configuration for the tick interval, window length, settling
      allowance, first-run lookback and OpenCost endpoint, and verify defaults
      produce hourly windows without configuration

## 6. Observability

- [ ] 6.1 Expose the sampler's lag as the age of the most recent recorded window,
      and verify it is queryable
- [ ] 6.2 Add an alert that fires while missed windows are still within upstream
      retention, and verify the rule evaluates against a deliberately stale ledger
- [ ] 6.3 Add a check comparing the recorded billable quantity against the higher
      of the recorded usage and request components, and verify it flags a window
      collected while the OpenCost exporter was unavailable

## 7. Verification

- [ ] 7.1 Run the sampler against the live cluster for several hours and verify
      recorded quantities for a window agree with the same window read directly
      from the OpenCost API
- [ ] 7.2 Verify recorded totals per owner agree with the `tenant-usage` dashboard
      for the same period
- [ ] 7.3 Confirm table and index growth is consistent with the ~250 MB/year
      estimate, and record the measured figure
