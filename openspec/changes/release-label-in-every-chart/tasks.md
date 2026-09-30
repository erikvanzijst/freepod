## 1. Contract test first

- [ ] 1.1 Replace `api/tests/test_curated_charts_ignore_release_id.py` with `api/tests/test_chart_release_label_contract.py`. It discovers every `products/*/chart`, reuses the dependency-resolving fixture and the per-chart minimum values, and declares datastores per chart by `# Source:` path (the table in design.md). Verify that it fails for all ten curated charts and passes for `custom`.
- [ ] 1.2 Cover the four assertions from design.md Decision 2: application pod templates are labeled; no selector or Service selector carries the label; datastore pod templates are unlabeled; a render without an ID emits no label. Verify by temporarily adding the include to a `custom` Service selector and to a datastore, and confirming the test names each offending chart and workload.

## 2. Charts

- [ ] 2.1 bookstack: add `bookstack.podLabels` to `_helpers.tpl`, pointing to `custom`'s helper for the rationale. Include it in `bookstack.yaml`'s pod template only, add `caelus.releaseId: ""` to `values.yaml`, and bump `Chart.yaml` to the next patch version. Verify that the contract test passes for bookstack.
- [ ] 2.2 helloworld: same as 2.1, for `deployment.yaml`. Verify with the contract test.
- [ ] 2.3 immich: same as 2.1, for `server.yaml` and `machine-learning.yaml`. Verify with the contract test.
- [ ] 2.4 lemmy: same as 2.1, for `lemmy.yaml`, `lemmy-ui.yaml`, `pictrs.yaml` and `proxy.yaml`. Verify with the contract test.
- [ ] 2.5 matrix: same as 2.1, for `statefulset.yaml` (Synapse) and `element-web.yaml`. Verify with the contract test and confirm that `helm template` still shows an unchanged StatefulSet `spec.selector`.
- [ ] 2.6 mattermost: same as 2.1, for `deployment.yaml`. Verify with the contract test.
- [ ] 2.7 naas: same as 2.1, for `deployment.yaml`. Verify with the contract test.
- [ ] 2.8 nextcloud: same as 2.1, for `nextcloud.yaml`. Verify with the contract test.
- [ ] 2.9 photoprism: same as 2.1, for `photoprism.yaml`. Verify with the contract test.
- [ ] 2.10 vaultwarden: same as 2.1, for `vaultwarden.yaml` and the `bootstrap-job.yaml` hook Job. Verify with the contract test.
- [ ] 2.11 Repoint `chart_version` in every `products/catalog/*.yaml` whose chart was bumped. Verify that the existing catalog tests pass and that each catalog version equals its `Chart.yaml` version.
- [ ] 2.12 Run `helm lint` over all ten charts. Verify that each one passes with no values supplied.

## 3. API: always pin

- [ ] 3.1 In `api/app/services/deployment_logs.py`, remove `CHARTS_RENDERING_RELEASE_LABEL`, `_chart_name`, `_renders_release_labels`, `LogAttributionUnavailable` and the refusal in `resolve_target`. Verify with `grep` that nothing references them.
- [ ] 3.2 In `api/app/services/reconcile.py`, always pass `release_id` to the failure-tail `LogTarget` and trim the comment. Verify that `test_reconcile_releases.py`'s fallback test is replaced by one asserting that a curated chart's tail is pinned.
- [ ] 3.3 Remove the "release pinning on a product that…" 400 case from the log endpoint docs in `api/app/api/users.py`.
- [ ] 3.4 Update `api/tests/test_deployment_log_api.py` and `test_deployment_log_stream.py`: delete the allowlist assertion and the "without release labels is reported" test, and add a test that pinning a curated-product deployment narrows the selector to the release. Verify that the API test suite passes.

## 4. Docs and cleanup

- [ ] 4.1 Update the comments in `custom`'s `values.yaml` and `_helpers.tpl` that say only this chart renders the label. Verify with `grep -rn "only this one\|only \`custom\`" products api/app`.
- [ ] 4.2 Add the release-label rule to `products/UPGRADING/SKILL.md` (every application pod carries `<chart>.podLabels`; datastores are declared in the contract test), so the nightly upgrader keeps it when it rewrites a chart. Verify that the section exists.
- [ ] 4.3 Delete `todo/033-releaseid-adoption-in-curated-charts.md`, which this change supersedes. Leave the rest of `todo/` alone. Verify that `git status` shows only that deletion under `todo/`.
- [ ] 4.4 Run the full API test suite and the CLI log tests. Verify that both pass.

## 5. Rollout

- [ ] 5.1 After merge, confirm that CI published the ten new chart versions to ghcr.io, and that each environment's catalog apply created the new canonical templates. Verify with `caelus list-templates` in the API pod.
- [ ] 5.2 Dev: run `caelus update-deployment --desired-template-id <canonical>` for each curated deployment, leaving the values flags out so stored values are kept. Verify that a pinned `freepod log --release N` returns output for one deployment of each product, and that no datastore pod restarted.
- [ ] 5.3 Prod: repeat 5.2 and verify the same way.
