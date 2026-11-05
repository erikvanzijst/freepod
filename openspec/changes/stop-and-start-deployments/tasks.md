# Tasks

## 1. Power data model

- [ ] 1.1 Add the `deployment_power` ORM model and the nullable `desired_power_id` / `applied_power_id` columns on `DeploymentORM`, with joined relationships as for the release pointers (design D1, D9). DDL per design § Schema and queries. Verify `uv run --no-sync python -c 'import app.models'` succeeds.
- [ ] 1.2 Write the Alembic migration: the table with `state` and `reason` check constraints, `ix_deployment_power_deployment`, both pointer columns and `on delete cascade` from power rows to deployment. Verify upgrade and downgrade on a scratch database, and that tests inserting an unknown state or reason fail.
- [ ] 1.3 Expose `power` (`desired`, `applied`, `reason`) on `DeploymentRead`, and mirror it in `ui/src/api/types.ts`. Verify with API tests for a never-stopped, a stopping, a stopped and a starting deployment, and with a test asserting that listing N deployments issues one query.

## 2. Stop and start service, API and `caelus`

- [ ] 2.1 Add `api/app/services/power.py` with `stop_deployment` and `start_deployment` (design D8): row lock first, idempotent no-op, `ready` check (`deployment_not_ready`), startable check for start (`not_startable`), power row with actor, pointer move, enqueue with reason `power`, rollback on `DeploymentInProgressException`. Add `JOB_REASON_POWER`. Verify with service tests covering every scenario in `deployment-power-api`.
- [ ] 2.2 Add `POST /users/{user_id}/deployments/{deployment_id}/stop` and `/start` to `api/app/api/users.py`, behind `require_self`, with the docstring conventions of the update route. Verify with API tests: owner, administrator (actor recorded), another user `403`, missing `404`, both coded `409`s and the in-progress `409`.
- [ ] 2.3 Add `caelus stop-deployment` and `caelus start-deployment` (`--user-id`, `--deployment-id`), recording no actor. Verify with `CliRunner` tests matching the API tests' outcomes.

## 3. Post-renderer suspended render

- [ ] 3.1 Add `--suspended`, `--release` and `--activator-host` to `api/app/post_render.py`. Implement the per-document step from design D4 (hook drop, replicas, Job/CronJob suspend, HPA and Pod drop, Ingress backend rewrite for `--hostname` only, the appended `<release>-caelus-activator` ExternalName). Keep untouched documents byte for byte. Verify with unit tests per document kind, a test that rules for other hosts and TLS blocks are unchanged, and a test that a normal render is unaffected.
- [ ] 3.2 Add a chart-rendering test (in conftest's `helm_charts` xdist group) that renders every catalog chart through the post-renderer with `--suspended`. It asserts: no hook documents, every Deployment and StatefulSet at 0 replicas, every own-host Ingress backend on the ExternalName, the App Studio preview Ingress untouched, and no chart already rendering a Service named `<release>-caelus-activator`. Verify it passes, and that it fails when the hook drop is disabled for Vaultwarden.

## 4. Reconciler power branch

- [ ] 4.1 Add `activator_host` to `config.py`. Give `HelmAdapter.helm_upgrade_install` the parameters `suspended` and `activator_host` and pass `--suspended`, `--release` and `--activator-host` through. If a suspended render is asked for with no `activator_host`, raise `IntegrityException` (design D7). Verify with provisioner unit tests on the built command line.
- [ ] 4.2 Implement design D3 in `DeploymentReconciler.reconcile`:
  - claim and record the release only when `applied_release_id ≠ desired_release_id`;
  - claim the power row (`started_at` write-if-null) when desired ≠ applied power;
  - render with the desired power;
  - on success, set `applied_power_id` and the power row's end time; on failure, the power row's error with status `error`.

  Verify with reconciler tests using the provisioner double: stop, start, a failed stop (no release row touched, applied power unchanged), an update to a stopped deployment (release recorded, suspended render), a combined release and power change in one Helm call, and a lease-reclaimed power reconcile keeping its first `started_at`.
- [ ] 4.3 Add the `AGENTS.md` architecture-notes entry for stopping and starting deployments (terse orientation plus spec and design links, per § Documentation Layering). Verify that the links resolve to the change's spec paths as they will be after sync.
- [ ] 4.4 Run the full `api/` suite (`uv run --no-sync pytest`, repo default `-n 8`) and verify it is green.

## 5. Activator daemon

- [ ] 5.1 Create `daemons/activator/` (own `go.mod`, added to `go.work` and `.dockerignore`, listed in `daemons/README.md`). It serves port 8080 as design D6 describes: 503 with `Cache-Control: no-store`; an HTML page built from the placeholder page's layout for `Accept: text/html`; `text/plain` otherwise; a plain 503 for WebSocket upgrades. It serves `/healthz` on 8081. Verify with `GOWORK=off go vet ./... && GOWORK=off go test ./...`, with tests for each response kind, a `Host` header containing markup being escaped, a hostname with a port, and `/healthz` on 8080 returning the stopped response.
- [ ] 5.2 Add `daemons/activator/README.md` (how to run and test it, plus spec links). Bump `daemons/VERSION`. Verify `scripts/build-images.sh --daemons` builds an image containing `/activator`.

## 6. Infrastructure

- [ ] 6.1 Add the `tf/app/activator/` module (design D7): namespace per workspace, 2-replica Deployment running `/activator` from `activator_image`, Service 80→8080, probes on 8081, NetworkPolicy admitting only Traefik on 8080. Output the Service FQDN. Wire it in `tf/app/main.tf`, add `activator_image` to `tf/app/variables.tf`, and pass `CAELUS_ACTIVATOR_HOST` into the caelus configmap for the API and the worker. Verify that `terraform validate` passes and `terraform plan` on dev shows only the new resources and the configmap change.
- [ ] 6.2 Set `providers.kubernetesIngress.allowEmptyServices: true` in `tf/deps/system/helm/traefik/values.yaml.tftpl`, with a short comment citing `deployment-power-reconciliation`. Verify that `terraform plan` in `tf/deps` shows only the Traefik release values changing.
- [ ] 6.3 Document the activator in `tf/app/README.md` (terse entry plus spec links). Verify the README renders and its links resolve.

## 7. `freepod` CLI

- [ ] 7.1 Add `freepod stop` and `freepod start` (design D10): project-recorded deployment only, environment check, no prompt for stop, `--no-wait`, a wait on `power.applied == power.desired` with `status = error` as failure, the already-in-state message, and coded-refusal messages. Verify with `CliRunner` tests covering every scenario in `cli-power`.
- [ ] 7.2 Make `freepod deploy` print the stopped notice when the settled deployment's desired power is `stopped`. Verify with a deploy test against a stopped deployment.
- [ ] 7.3 Bump the minor `__version__` in `cli/src/freepod/__init__.py`. Run `npm run cli:reference` in `ui/docs` and add a "Stopping and starting" section to `ui/docs/developers/deployments-and-releases.md`. Verify that the `cli` test suite and `npm run build` in `ui/docs` pass and that `developers/cli-reference.md` is current.

## 8. Dashboard

- [ ] 8.1 Extend `deploymentView` with the Stopped, Stopping and Starting labels, and with `canStop` and `canStart` derived from `status` and `power`. Verify with `deploymentView.test.ts` cases for each label and action rule in `deployment-power-ui`.
- [ ] 8.2 Add Stop (with a confirmation dialog extracted into its own component) and Start to `DeploymentRow`, wired through API client functions in `ui/src/api/`, showing refusals in the row. Verify with `DeploymentRow.test.tsx` cases: stop confirmed, stop canceled, start, and a `409` shown.
- [ ] 8.3 Make the dashboard's `refetchInterval` also poll while any deployment's desired and applied power differ. Verify with a Dashboard test that polling starts on Stopping and stops on Stopped.
- [ ] 8.4 Add `ui/docs/apps/managing/stopping-an-app.md` on stopping and starting an app, following § User Documentation. Verify with `npm run build` in `ui/docs`.

## 9. Integration on dev

- [ ] 9.1 Deploy to dev in the order of the design's Migration Plan, then on dev:
  - stop a `custom` deployment and confirm its hostname serves the 503 stopped page, with the Helm release history showing replicas 0;
  - start it and confirm the page gives way to a 503 from Traefik and then the app, without a 404;
  - update it while stopped and confirm it stays stopped.

  Record the observed transitions in the change's notes.
- [ ] 9.2 On dev, stop a Vaultwarden deployment (verify the hook is dropped and the stop succeeds), a Matrix deployment (verify every path serves the stopped page), and an App Studio deployment (verify the preview host is untouched and answers 503). Start each and verify it comes back healthy.

## Workflow follow-up

- After review and merge, apply `tf/app` on prod, then push the `freepod-v*` tag for the new client version.
- Archive the change with `openspec archive`, syncing the delta specs into `openspec/specs/`.
