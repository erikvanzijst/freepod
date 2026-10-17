# Tasks

## 1. Builder: detect and report

- [x] 1.1 Add `serves_static_site(plan_path)` to `products/custom/builder/build.py`, which matches the plan's deploy start command exactly against Railpack's two Caddy commands and returns false for anything missing, unreadable or unexpected. Report `static_site` beside `image` in the termination message; a Dockerfile build reports false. Verify with tests in `api/tests/test_builder_script.py` using real v0.36.4 plans (static HTML, Vite SPA, Node server, Python), a Dockerfile build, and missing, garbled and wrongly shaped plans.
- [x] 1.2 Bump `products/custom/builder/VERSION` to 0.5.0 and the `builder_image` default in `tf/app/variables.tf`, document the new field in the builder README's termination message section, and verify the builder tests pass.

## 2. Build record and worker

- [x] 2.1 Add `build.static_site` (boolean, `NOT NULL DEFAULT false`) to `BuildORM` and an Alembic migration, and verify `alembic upgrade head` and downgrade against the test database plus a migration test showing existing builds read false; `test_schema_drift` stays green.
- [x] 2.2 Parse the verdict in `build_jobs.py` (only JSON `true` counts) and store it in the build worker's success path. Verify with worker tests covering a static report, an absent verdict and a malformed one.

## 3. Reconciler projection

- [x] 3.1 Inject `caelus.build.staticSite` on every apply and `caelus.build.image` when the release names a succeeded build, taken from the release's own build. Verify with reconciler tests covering a static build, a non-static build, no build, and user values that try to set `caelus.build`; update the exact-values happy-path assertion.

## 4. Chart

- [x] 4.1 Add `staticSiteResources` (10m CPU, 16Mi memory) and a `caelus.build` default to `products/custom/chart/values.yaml` and `values.schema.json`, choose the app container's requests in a helper that compares `caelus.build.image` with `image`, and bump the chart to 0.14.0 and `products/catalog/custom/custom.yaml` to match. Verify with `test_custom_chart.py` render tests for: static match, static with a different image, non-static, placeholder, and the absence of limits.

- [x] 4.2 State the lower static-site minimum in `ui/docs/developers/usage-and-billing.md` (12m CPU and 32Mi across the app and SSH sidecar at the current rates), and verify the figure against the usage rates.

## 5. Integration

- [x] 5.1 Run the full api suite (`cd api && uv run pytest`) and `openspec validate static-site-requests --strict`. Both must be green.

## Workflow follow-up

- Publish builder 0.5.0 and chart 0.14.0 before the rollout whose catalog apply references the chart, then apply the `builder_image` pin per environment.
- Archive the change once it is live.
