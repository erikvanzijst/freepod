## 1. Builder measures itself

- [ ] 1.1 Add a cgroup reader to `products/custom/builder/build.py`: `cpu.stat usage_usec`, `memory.peak`, and working set as `memory.current` minus `memory.stat inactive_file`; verify with unit tests in `api/tests/test_builder_script.py` against fixture cgroup files
- [ ] 1.2 Add a background thread integrating working set every 2 s into byte-seconds, stopped at exit, and record the run's UTC start and end; verify with a test driving the integrator over a scripted sequence of readings
- [ ] 1.3 Put the `usage` object (design D2) in the termination message on success and on failure, including the unexpected-exception path; verify with tests on each exit path and that the message stays under 4 KiB
- [ ] 1.4 Bump `products/custom/builder/VERSION`, and document the new termination-message field in the builder README; verify by reading both back

## 2. Build data model

- [ ] 2.1 Add the usage columns and `usage_recorded_at` to `BuildORM` (design D3), with a partial index on `usage_recorded_at IS NULL`, and write the migration, which also sets `usage_recorded_at` on every build already terminal (design D6); verify `tests/test_schema_drift.py` passes and a migration test shows existing terminal builds marked, open ones left unmarked, and the downgrade round trip
- [ ] 2.2 Add `SubjectKind.BUILD`; verify an existing ledger test still round-trips and a `build` subject can be written

## 3. Build worker stores and records usage

- [ ] 3.1 Parse the termination message's `usage` on both success and failure, and store it on the build in the transaction that finishes it, marked measured; verify with worker tests for a succeeded build, a failed build that reported, and one that did not
- [ ] 3.2 Implement the per-window computation (design D5) as a pure function of the build row, including the estimated case (design D7) that omits usage averages; verify with unit tests for a build within one hour, one across an hour boundary, a light and a heavy build, and an estimated build
- [ ] 3.3 Add the recording pass (design D4): select settled, unrecorded builds that ran a Job, write their `build` subject and samples and set `usage_recorded_at` in one transaction; verify with tests that a build is not recorded before its window settles, is recorded once after, survives a simulated crash mid-record, and is recorded once when two passes race
- [ ] 3.4 Run the recording pass from the build worker's loop; verify with a worker-loop test that a finished build's samples appear after the settle time

## 4. Usage sampler

- [ ] 4.1 Derive `last_recorded_window` from `container` subjects only; verify with a test where a `build` sample in a newer window does not advance the resume position
- [ ] 4.2 Skip allocations in `settings.builds_namespace`, keeping the other environment's builds namespace as platform overhead; verify with sampler tests for both namespaces

## 5. Reporting

- [ ] 5.1 Verify the usage report attributes a `build` subject's samples to its deployment, owner and product with no reporting change, including after the deployment is deleted; verify with a test in `tests/test_usage_report.py`

## 6. Documentation

- [ ] 6.1 Update AGENTS.md's usage bullet to say builds are recorded by the build worker from their own measurements; verify by reading it back

## 7. Rollout verification

- [ ] 7.1 Run the full API test suite and verify it passes
- [ ] 7.2 On dev, after publishing the builder image and rolling out: deploy a test app, and verify that after the window settles its build has a `build` subject attributed to the deployment, samples whose CPU seconds match what the build reported, and that the sampler recorded nothing in `caelus-builds-dev`
