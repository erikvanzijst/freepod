# Tasks

## 0. Vaultwarden without a hook, and the hook ban

- [x] 0.1 Rewrite `products/vaultwarden/chart` per design D6:
  - delete `templates/bootstrap-job.yaml`;
  - add `OWNER_EMAIL`, `READY_TIMEOUT` and the `postStart` script to the `vaultwarden` container in `templates/vaultwarden.yaml`, and move the comment block;
  - remove `bootstrap.image` from `values.yaml` and `values.schema.json`, and reword `bootstrap.readyTimeoutSeconds`;
  - bump `Chart.yaml` to 3.5.0;
  - update `products/vaultwarden/README.md`.

  Verify that `helm lint` and `helm template` with the catalog's system values render no Job and a `postStart` hook containing the five steps.
- [x] 0.2 Set `template.chart_version: 3.5.0` in `products/catalog/vaultwarden/vaultwarden.yaml`. Verify that `caelus catalog lint` passes.
- [x] 0.3 Add a chart-rendering test (in conftest's `helm_charts` xdist group) that renders every catalog chart with its catalog system values and asserts no document carries a `helm.sh/hook` annotation. Verify that it passes, and fails against chart 3.4.7's `bootstrap-job.yaml`.
- [x] 0.4 On dev, deploy a fresh Vaultwarden from chart 3.5.0 (a hand push must use a version never published), and check:
  - the owner's invitation arrives, and the container log shows the "invited" line;
  - deleting the pod logs "already invited or registered";
  - a wrong admin token restarts the container, and the release rolls back.

  Record the results in the change's notes.

## 1. Power data model

- [x] 1.1 Add the `deployment_power` ORM model, and the nullable `desired_power_id` / `applied_power_id` columns on `DeploymentORM` with joined relationships as for the release pointers (design D1, D10). DDL per design § Schema and queries. Verify that `uv run --no-sync python -c 'import app.models'` succeeds.
- [x] 1.2 Write the Alembic migration: the table with the `state` (`running`, `stopped`) and `reason` (`manual`, `payment`) check constraints, `ix_deployment_power_deployment`, both pointer columns, and `on delete cascade` from power rows to deployment. Verify upgrade and downgrade on a scratch database, and that inserting an unknown state or reason fails.
- [x] 1.3 Expose `power` (`desired`, `applied`, `reason`) on `DeploymentRead`, and mirror it in `ui/src/api/types.ts`. Verify with API tests for a never-stopped, a stopping, a stopped and a starting deployment, and with a test asserting that listing N deployments issues one query and makes no `kubectl` call.

## 2. Stop and start service, API and `caelus`

- [x] 2.1 Add `api/app/services/power.py` with `stop_deployment` and `start_deployment` (design D9):
  - row lock first;
  - an idempotent no-op;
  - the `ready` check (`deployment_not_ready`);
  - the startable check for start (`stopped` with reason `manual`, else `not_startable`);
  - the power row with the actor;
  - the pointer move;
  - the enqueue with reason `power`;
  - rollback on `DeploymentInProgressException`.

  Add `JOB_REASON_POWER`. Verify with service tests covering every scenario in `deployment-power-api`.
- [x] 2.2 Add `POST /users/{user_id}/deployments/{deployment_id}/stop` and `/start` to `api/app/api/users.py`, behind `require_self`, with the docstring conventions of the update route. Verify with API tests:
  - the owner;
  - an administrator, with the actor recorded;
  - another user gets `403`;
  - a missing deployment gets `404`;
  - both coded `409`s and the in-progress `409`.
- [x] 2.3 Add `caelus stop-deployment` and `caelus start-deployment` (`--user-id`, `--deployment-id`), recording no actor. Verify with `CliRunner` tests matching the API tests' outcomes.

## 3. Post-renderer stopped render

- [x] 3.1 Add `--render=normal|stopped`, `--release`, `--parking-host` and `--parking-port` to `api/app/post_render.py`, and implement the stopped step from design D4:
  - replicas to 0;
  - Job and CronJob suspended;
  - HPAs and bare Pods dropped;
  - the Ingress backend rewrite for `--hostname` only, case-insensitive;
  - the appended `<release>-caelus-parking` ExternalName.

  `--render=stopped` without `--parking-host` is a usage error. Keep untouched documents byte for byte. Verify with:
  - unit tests per document kind;
  - a test that rules for other hosts, annotations and TLS blocks are unchanged;
  - a test that the default `normal` render is byte-identical to today's.
- [x] 3.2 Add a chart-rendering test (in the `helm_charts` xdist group) that renders every catalog chart through the post-renderer with `--render=stopped`. It asserts:
  - every Deployment and StatefulSet is at 0 replicas;
  - every own-host Ingress backend is on the ExternalName;
  - the App Studio preview Ingress is untouched;
  - no chart renders a Service named `<release>-caelus-parking`.

  Verify that it passes.

## 4. Reconciler power branch

- [x] 4.1 Add `parking_host` and `parking_port` to `config.py`. Give `HelmAdapter.helm_upgrade_install` the parameters `render`, `release_name`, `parking_host` and `parking_port`, and pass the post-render flags through. If `render == "stopped"` and `parking_host` is empty, raise `IntegrityException` (design D8). Verify with provisioner unit tests on the built command line.
- [x] 4.2 Add `provisioner.sweep_stopped_workloads(namespace)` (design D5): list Deployments and StatefulSets in the namespace, and `kubectl scale --replicas=0` each one above 0. Verify with a unit test against a `kubectl` runner double, covering workloads at 0, at 1, and a failing scale.
- [x] 4.3 Implement design D3 in `DeploymentReconciler.reconcile`:
  - claim and record the release only when `applied_release_id ≠ desired_release_id`;
  - claim the power row (`started_at`, write-if-null) when desired ≠ applied power;
  - render `stopped` or `normal` from the desired power;
  - sweep after a successful stopped apply;
  - on success, set `applied_power_id` and the power row's end time;
  - on failure, in one transaction, record the power row's end time and error, move `desired_power_id` back to `applied_power_id`, and set status `error`.

  Verify with reconciler tests using the provisioner double:
  - stop and start;
  - a failed stop: no release row touched, applied power unchanged, desired power reverted to applied;
  - a failed stop followed by a deploy: normal render, `ready` and running, and the failed row's `ended_at` and `error` unchanged;
  - a failed start followed by a deploy: stopped render, `ready` and stopped;
  - an update to a stopped deployment: release recorded, stopped render, sweep run;
  - a combined release and power change in one Helm call;
  - a lease-reclaimed power reconcile keeping its first `started_at`;
  - a failed sweep failing the reconcile.
- [x] 4.4 Add the `AGENTS.md` architecture-notes entry for stopping and starting deployments: a terse orientation plus spec and design links, per § Documentation Layering. Verify that the links resolve to the spec paths as they will be after sync.

## 5. Parking page in the API

- [x] 5.1 Add `api/app/parking.py` with `ParkingGuard`, a pure ASGI middleware (design D7):
  - the guard is off when `settings.domain` is empty;
  - it passes loopback peers (`scope["client"]` `127.0.0.1` or `::1`);
  - it passes a `Host` equal to `settings.domain`, after lowercasing and stripping the port;
  - otherwise it answers 503 with `Cache-Control: no-store`: an HTML page for `GET` with `Accept` containing `text/html` and no `Upgrade`, `text/plain` for everything else, and `websocket.close` before accept for WebSocket scopes.

  Build the HTML with `string.Template` and `html.escape` from a copy of `products/custom/placeholder/index.html`'s layout. Install it last in `api/app/main.py`, so it is outermost. Verify with tests:
  - a foreign host with `X-Auth-Request-Email` on `/api/users/me` gets the parking response, and no route or dependency runs;
  - every method;
  - HTML versus plain text;
  - a `Host` header containing markup is escaped;
  - a host with a port;
  - the platform domain passes, in any letter case;
  - a loopback peer passes;
  - `X-Forwarded-For: 127.0.0.1` from a non-loopback peer gets the parking response;
  - a WebSocket to a foreign host is refused;
  - `settings.domain` empty passes everything;
  - `/healthz` and `/api/openapi.json` on a foreign host get the parking response.
- [ ] 5.2 Run the full `api/` suite (`uv run --no-sync pytest`, repo default `-n 8`). Verify it is green, with every existing test still passing behind the guard.

## 6. Infrastructure

- [x] 6.1 In `tf/app/caelus/configmap.tf`, set `CAELUS_PARKING_HOST = "caelus-api.${var.namespace}.svc.cluster.local"` and `CAELUS_PARKING_PORT = "8000"` for the API and the worker (design D8). Verify that `terraform validate` passes, and that `terraform plan` on dev shows only the configmap change.
- [x] 6.2 Confirm `--providers.kubernetesingress.allowEmptyServices=true` is in the live Traefik's arguments. Add a comment in `tf/deps/system/helm/traefik/values.yaml.tftpl` stating that `deployment-power-reconciliation` relies on the chart's default `allowEmptyServices: true` (design D13). Verify that `terraform plan` in `tf/deps` shows no change.
- [x] 6.3 Document the parking page in `tf/app/README.md` (a terse entry plus spec links). Verify that the README's links resolve.

## 7. `freepod` CLI

- [x] 7.1 Add `freepod stop` and `freepod start` (design D11):
  - the project-recorded deployment only;
  - the environment check;
  - no prompt for stop;
  - `--no-wait`;
  - a wait on `power.applied == power.desired`, with `status = error` as failure;
  - the already-in-state message;
  - messages for the coded refusals.

  Verify with `CliRunner` tests covering every scenario in `cli-power`.
- [x] 7.2 Make `freepod deploy` print the stopped notice when the settled deployment's desired power is `stopped`. Verify with a deploy test against a stopped deployment.
- [x] 7.3 Bump the minor `__version__` in `cli/src/freepod/__init__.py`. Run `npm run cli:reference` in `ui/docs`, and add a "Stopping and starting" section to `ui/docs/developers/deployments-and-releases.md`. Verify that the `cli` test suite and `npm run build` in `ui/docs` pass, and that `developers/cli-reference.md` is current.

## 8. Dashboard

- [x] 8.1 Extend `deploymentView` with the Stopped, Stopping and Starting labels, and with `canStop` and `canStart` derived from `status` and `power` (design D12). Verify with `deploymentView.test.ts` cases for each label and action rule in `deployment-power-ui`.
- [x] 8.2 Add Stop (with a confirmation dialog extracted into its own component) and Start to `DeploymentRow`, wired through API client functions in `ui/src/api/`, showing refusals in the row. Verify with `DeploymentRow.test.tsx` cases: stop confirmed, stop canceled, start, and a `409` shown.
- [x] 8.3 Make the dashboard's `refetchInterval` also poll while any deployment's desired and applied power differ. Verify with a Dashboard test that polling starts on Stopping and stops on Stopped.
- [x] 8.4 Add `ui/docs/apps/managing/stopping-an-app.md` on stopping and starting an app, following § User Documentation. Verify with `npm run build` in `ui/docs`.

## 9. Integration on dev

- [x] 9.1 Run the design's Migration Plan step 0 in dev, and run the prerequisite query until it returns no rows.
- [x] 9.2 Deploy to dev per Migration Plan steps 1–2, and run every check in step 3. Record the observed transitions and the forged-header results in the change's notes.

## Workflow follow-up

- Before the prod API rollout, run Migration Plan step 0 on prod, and the prerequisite query until it returns no rows.
- After review and merge, apply `tf/app` on prod, then push the `freepod-v*` tag for the new client version.
- Archive the change with `openspec archive`, syncing the delta specs into `openspec/specs/`, and repoint the rationale links in `AGENTS.md` and `tf/app/README.md` at the archived `design.md`.
