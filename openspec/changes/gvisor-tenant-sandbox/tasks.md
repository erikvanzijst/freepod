# Tasks

## 1. RuntimeClass in Terraform

- [x] 1.1 Add a `tf/deps/sandbox` module with a `kubernetes_manifest` RuntimeClass `gvisor`: handler `runsc`, `scheduling` pinned to `caelus.dev/node-pool=tenant` with the pool's `NoSchedule` toleration, and `overhead.podFixed` of 32Mi memory and 10m CPU (design D1, D5). Wire it from `tf/deps/main.tf`. Verify with `terraform validate`.
- [x] 1.2 Import the hand-made RuntimeClass into `module.sandbox` and run `terraform plan -target=module.sandbox`. Verify the plan only adds `overhead` and changes nothing else.
- [x] 1.3 Apply with `terraform apply -target=module.sandbox`. Verify `kubectl get runtimeclass gvisor -o yaml` shows the overhead, and that a throwaway pod using it gets `spec.overhead` and is scheduled onto the tenant node.
- [x] 1.4 Document the sandbox in `tf/deps/README.md` (design D7): what the RuntimeClass is for; the tenant node's runsc install (pinned release, tarball and checksum), the containerd `config-v3.toml.tmpl` and `/etc/containerd/runsc.toml`; how to upgrade runsc; that sandboxed pods stay Pending while the tenant pool is down. Verify the install steps match what is on the node (`runsc --version`, the rendered `config.toml`).

## 2. `custom` chart

- [x] 2.1 Add a `runtimeClassName` system value to `products/custom/chart`: empty default in `values.yaml`, an entry in `values.schema.json` described like `nodePool`, and `runtimeClassName` rendered on the app pod when set. Verify with `helm template` with and without the value.
- [x] 2.2 Render `hostUsers: false` only when `runtimeClassName` is empty (design D4), and update the pod comment to say why. Verify with `helm template` both ways.
- [x] 2.3 Extend `api/tests/test_custom_chart.py`: `runtimeClassName` rendered when set and absent when empty; `hostUsers: false` on the default runtime and absent under `gvisor`; the `nodePool` tests still pass. Verify by running the module.
- [x] 2.4 Bump `products/custom/chart/Chart.yaml` to 0.16.0. Update the `custom` README's pod description to say where the app runs and that it requires the tenant pool. Verify that `helm lint` passes and the README matches the rendered pod.

## 3. App Studio chart

- [x] 3.1 Add the `runtimeClassName` system value to `products/appstudio/chart` (empty default in `values.yaml`, rendered on the StatefulSet's pod when set), with `hostUsers: false` rendered only when it is empty. Verify with `helm template` both ways.
- [x] 3.2 Extend `api/tests/test_appstudio_chart.py` with the same two runtime cases as 2.3. Verify by running the module.
- [x] 3.3 Bump `products/appstudio/chart/Chart.yaml` to 0.2.20. Verify `helm lint` passes.

## 4. Catalog

- [x] 4.1 Set `runtimeClassName: gvisor` in `template.system_values` and the new `chart_version` in `products/catalog/custom/custom.yaml` (0.16.0) and `products/catalog/appstudio/appstudio.yaml` (0.2.20). Verify `test_catalog_charts.py` and `test_catalog_format.py` pass.
- [x] 4.2 Confirm a tenant cannot set the runtime: deployment values carrying `runtimeClassName` are rejected by each product's tenant-facing `values_schema`. Verify with a test in the catalog or chart test module.
- [x] 4.3 Run the full `api/` suite and verify it is green.

## 5. Dev rollout

- [x] 5.1 Publish `custom` 0.16.0 and App Studio 0.2.20, apply the catalog to dev, and upgrade every dev `custom` and App Studio deployment. Verify each pod has `runtimeClassName: gvisor`, runs on the tenant node, and `dmesg` inside it reports gVisor.
- [x] 5.2 Exercise a dev `custom` app: hostname serves; `freepod shell` opens an app-container session; `freepod cp` and `freepod log` work; the app reaches its database through PgBouncer and its bucket. Verify each by hand and record the results.
- [x] 5.3 Exercise a dev App Studio instance that already holds projects: existing projects open with their files intact; the agent can `apt install` a package and run a preview. Verify by hand and record the results.
- [ ] 5.4 Verify isolation and metering on dev: the deployment's NetworkPolicy blocks a denied egress destination and an unadmitted ingress source; OpenCost's `/allocation` reports non-zero usage for the sandboxed containers over a settled hour.

## 6. Prod rollout

- [ ] 6.1 Apply the catalog to prod and upgrade every prod `custom` and App Studio deployment. Verify every such pod runs under `gvisor` on the tenant node and every hostname answers.
- [ ] 6.2 After the first settled hour, compare those deployments' usage-ledger rows with the hour before the upgrade. Verify usage is non-zero and in line with before.

## Workflow follow-up

- Archive the change after merge and prod rollout, syncing both delta specs.
- Fill in the new `tenant-sandbox-runtime` main spec's Purpose if archive leaves a placeholder.
- Repoint the Rationale link in `tf/deps/README.md`'s Sandboxed runtime section at the archived design.md.
