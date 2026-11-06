# Design

## Context

This change is phase 1 of a subsystem with two independent mechanisms:
- **Stop and start**, owned by Freepod: the power ledger, the reconciler and a post-render step. This change.
- **Pause when idle and wake on traffic**, delegated to Sablier in a later change.

The appendix states what that phase needs from this one. Every fact below was checked against the repository or the dev cluster on Nov 5–6, 2026.

**Releases and the reconciler**
- **Every reconcile is a rollout.** `DeploymentReconciler.reconcile` always claims the desired release (`_claim_desired_release`) and records its outcome (`_record_release_outcome`). The release ledger forbids rewriting those columns (`deployment-release-ledger`, "No release column is revised after it is written"). Today that never conflicts, because the only reconciles are create, update and delete, and each comes with a new release.
- **Releases use server-side apply.** They are applied by Helm 4.3.0 with `--atomic --wait --timeout 300s` (`HELM_TIMEOUT_SEC = 300` in `api/app/services/reconcile.py`) and report `APPLY_METHOD: server-side apply`.
- **Lease reclaim.** A worker that dies mid-reconcile leaves its job `running`. Another worker reclaims it once `locked_at` is older than `reconcile_job_lease_seconds` (600 s) and runs the whole reconcile again (`_claimable_clause` in `api/app/services/jobs.py`). Every "started" timestamp is therefore written only if still null.
- **Worker concurrency.** The worker runs `caelus worker --concurrency 4`, one replica per environment.

**The post-renderer**
- **It already sees everything.** `api/app/post_render.py` runs on every `helm upgrade` as a Helm 4 post-renderer plugin, with `--image`, `--deadline-seconds` and `--hostname` passed by `api/app/provisioner.py`. It injects the egress gate into every pod template. Under Helm 4.3 it also receives hook documents.

**Replicas under server-side apply** (measured on dev)
- Kubernetes defaults a missing `spec.replicas` to 1.
- When Helm, as the field's last owner, stops applying it, the field is removed and defaults to 1.
- Applying `replicas: 0` makes Helm the owner of 0.
- Every Helm-managed workload on the cluster is at 1 replica. No catalog chart renders an HPA, CronJob or bare Pod.

**Hooks**
- The only `helm.sh/hook` document in any catalog chart is Vaultwarden's `post-install,post-upgrade` bootstrap Job (`products/vaultwarden/chart/templates/bootstrap-job.yaml`, chart 3.4.7). It invites the owner through the admin API. Against a deployment at 0 replicas it would fail after its 120 s readiness wait and roll the release back.

**Edge (Traefik)**
- **One Traefik for the cluster.** It is a single replica in `tf/deps/system/helm/traefik`, chart 41.5.0 (Traefik v3.7.13), shared by dev and prod.
- **Routers without endpoints already answer 503.** The chart defaults `providers.kubernetesIngress.allowEmptyServices` to true, and the live Traefik runs with `--providers.kubernetesingress.allowEmptyServices=true`. A router whose Service has no ready endpoints is kept and answers 503, not 404.
- **ExternalName Services are allowed** (`allowExternalNameServices: true`).
- **How middlewares attach.** App Ingresses attach middlewares through `traefik.ingress.kubernetes.io/router.middlewares`, first entry outermost. The custom and App Studio charts put `strip-identity` and `app-auth` there.

**The API**
- **It trusts identity headers.** The API trusts `X-Auth-Request-Email` and `X-Auth-Request-User` (`get_current_user` in `api/app/deps.py`). They are set by oauth2-proxy's forward-auth on the API's own Ingresses, which are host `settings.domain` (`freepod.eu`, `dev.freepod.eu`) with paths `/api` and `/api/webhooks`.
- **Only Traefik can reach it.** Its NetworkPolicy, `caelus-api-ingress`, admits only `kube-system` pods labeled `app.kubernetes.io/name=traefik` on 8000.
- **Nothing in the cluster calls the API's Service by name.** `ui/nginx.conf` proxies nothing; the workers use the database.
- **The pod has no probes.**
- **How it runs.** It runs `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1`, one replica. Its Service is `caelus-api`, port 8000.

**Namespaces**
- Each deployment has its own namespace (`uq_deployment_namespace`), unique across dev and prod.

## Goals / Non-Goals

**Goals:**
- Owners can stop and start a deployment, keeping all of its data, through the API, `caelus`, `freepod` and the dashboard.
- A stopped deployment's hostname answers a branded 503, and its own hostname can never reach an API route.
- Build the parts the pause phase reuses unchanged:
  - the power ledger and its pointers;
  - the reconciler's power branch;
  - the post-renderer's render modes;
  - the 503 behavior at the edge;
  - the parking page.
- Prove that a stopped release survives Helm's server-side apply across later upgrades.

**Non-Goals:**
- Pausing when idle and waking on traffic (the next change, with Sablier).
- Stopping for payment arrears. The `payment` reason exists, and start already refuses it.
- Capacity policy for nodes that cannot hold every deployment running.
- Skipping major versions on products that cannot, such as Nextcloud, when several rollouts reach a stopped deployment.

## Decisions

### D0. One vocabulary on every surface

| Word | Kind | Meaning |
| --- | --- | --- |
| **Stop** | Action (owner, admin, operator) | Takes the deployment offline. Nothing runs, and only Start runs it again. |
| **Start** | Action (owner, admin, operator) | Runs a stopped deployment again. |
| **Stopped** | Recorded power state | The result of Stop. |
| **Running** | Recorded power state | Anything not stopped. |
| **Stopping**, **Starting** | Transitional status | Desired and applied power differ. |

These are the only words used in the dashboard, the API (routes, state values, error codes), `caelus`, `freepod` and the docs.

- **Not "resume" or "suspend."** "Resume" implies carrying on where something left off. "Suspend" means different things elsewhere: Docker freezes processes, Fly snapshots memory, Render never wakes.
- **Paused is not a power state.** The pause phase adds **Paused** and **Pausing** as runtime statuses of a *running* deployment, observed from the cluster. There is no manual Pause or Wake action: a paused app wakes when visited.
- **A stopped app is never started as a side effect,** whether by traffic, SSH, a CLI deploy or a platform rollout.

### D1. Power is a ledger beside the release ledger, not inside it

Rows in `deployment_power` hold intent and outcome:
- **Intent:** `state` (`running` or `stopped`), `reason` (`manual` or `payment`), `actor_user_id` (null for the platform) and `created_at`.
- **Outcome:** `started_at`, `ended_at` and `error`.

`deployment.desired_power_id` and `deployment.applied_power_id` point into it, and null means `running`. The DDL is in Schema and queries, below.

- **Alternative: a new release per power change.** Rejected. It would churn `freepod releases`, and image retention, which walks releases, would see changes that have nothing to do with deploys.
- **Alternative: enum columns on `deployment`.** Rejected. The UI and later phases need the reason, actor and outcome of the latest change, and a ledger keeps their history for free.

Unlike the release pointers, the power pointers are nullable. The circular foreign key therefore needs no `DEFERRABLE` treatment (insert the row, then move the pointer), and no backfill.

### D2. Power changes require `status = ready`

- **Why it makes the reconciler branch cheap.** Only a successful reconcile sets `ready`, and it sets `applied_release_id` in the same transaction. So when a deployment is `ready`, its desired release is its applied release. A power-only reconcile therefore re-renders exactly what is running, and nothing has to reconstruct values from a snapshot.
- **Failed deployments are exempt.** A deployment in `error` is in a state nobody fully knows, so the platform does not apply power changes to it.
- **The power functions do not change `status`.** It keeps describing the provisioning lifecycle: a stopped deployment is still `ready`, which leaves the transition table in `deployment-payment-states` untouched.
- **Stopping and Starting** are "`ready`, desired ≠ applied power", which is how the UI tells Stopping from Stopped and Starting from Running.
- **Recovery.** A stopped deployment that a failed platform rollout turned to `error` is recovered by the owner deploying, which fixes it and leaves it stopped, and then starting it.
- **Concurrent updates.** `update_deployment` racing a power change still gets the existing 409, from `uq_open_reconcile_job_per_deployment` at enqueue.

### D3. The reconciler stays level-triggered: rollout iff `applied_release_id ≠ desired_release_id`

`reconcile()` decides from the pointers, not from the job's reason:

```python
release = deployment.desired_release
rollout = deployment.applied_release_id != release.id
if rollout:
    self._claim_desired_release(deployment)          # unchanged, write-if-null
power = deployment.desired_power                     # None means running
power_change = deployment.desired_power_id != deployment.applied_power_id
if power_change:
    claim_power(power)                               # started_at, write-if-null
mode = "stopped" if power is not None and power.state == "stopped" else "normal"
helm_upgrade_install(..., render=mode, release_name=deployment.name, ...)
if mode == "stopped":
    provisioner.sweep_stopped_workloads(deployment.namespace)   # D5
on success:  applied_release_id = release.id (if rollout)
             applied_power_id = desired_power_id
             power.ended_at = now (if power_change)
on failure:  status = error, last_error; power.ended_at, power.error (if power_change);
             desired_power_id = applied_power_id (if power_change);
             release outcome only if rollout
```

- **The release used for values.** `_reconcile_apply` keeps using `release` for the vars Secret and the release overrides. When `rollout` is false, that release is the applied one.
- **Combined changes.** A rollout and a power change in one reconcile are one Helm apply, with both outcomes recorded from it.
- **Lease reclaim** still sees `applied ≠ desired` and claims again, write-if-null.
- **The `power` reason.** The power service functions enqueue jobs with a new reason, `power` (`JOB_REASON_POWER`). It is informational only, because the reconciler never branches on the reason.
- **The worker needs no change.** A failed power reconcile returns `status = error`, and the worker marks the job failed.
- **A failed power change is finished.** When a reconcile with a power change fails, the reconciler moves `desired_power_id` back to `applied_power_id`, in the same transaction that writes the row's `ended_at` and `error` and sets `status = error`.
  - **It matches the cluster.** `--atomic` has rolled the release back to the applied power, so desired, applied and the cluster agree.
  - **"Written once" holds.** Each power row gets exactly one outcome, and the failed row stays in the ledger as the record of the attempt.
  - **The owner's way out works as expected.** The owner recovers from `error` by deploying, and that deploy renders in the applied power. A stop that failed never takes effect later as a side effect of an unrelated deploy. A failed start reverts to the `stopped` row, so the deploy renders stopped and the deployment stays stopped.
  - **Retrying is a new request.** Once the deployment is `ready` again, the owner stops or starts it again, which writes a fresh row.
  - **The dashboard shows the failure.** With desired equal to applied and status `error`, it shows the existing error label and `last_error`, not a Stopping or Starting that never ends.
  - **Lease reclaim is unaffected.** A worker that dies records no outcome, so the reclaimed job still sees desired ≠ applied and carries on.
  - **A failed combined reconcile** records the failure on both rows. The desired power reverts, and the desired release stays pointed at the failed release, as for any failed rollout.
  - **Who moves the pointer.** The power service moves `desired_power_id` forward; only a failed reconcile moves it back, and only to `applied_power_id`.
  - **Rejected alternatives:** retrying the old row on the next reconcile, which rewrites its outcome, loses the first failure and stops the app by surprise; and having the reconciler insert a retry row, which would make the reconciler create intent, something it never does for releases either.
- **When the power row's outcome is recorded.** Only when `desired_power_id` is set and differs from `applied_power_id`. A rollout to a deployment that is already stopped leaves the power row as it was.
- **Rollouts to a stopped deployment** are rendered stopped and recorded as succeeded without the new version booting. A broken release surfaces at the next start, as a failed start with Helm's error and an atomic rollback. That is preferred over starting every stopped deployment on every rollout.

### D4. The stopped render is one more post-render mode

`post_render.py` gains:

| Flag | Value |
| --- | --- |
| `--render=normal\|stopped` | Default `normal`. The pause phase adds `pausable`. |
| `--release=<name>` | The Helm release name, which Helm does not pass to post-renderers. It names the platform's objects. |
| `--parking-host=<fqdn>` | `settings.parking_host`. Required with `--render=stopped`. |
| `--parking-port=<port>` | `settings.parking_port` (8000). Required with `--render=stopped`. |

`provisioner.helm_upgrade_install` passes them as `--post-renderer-args`, as it already does for `--image`, `--deadline-seconds` and `--hostname`. With `--render=stopped`, `render()` runs a per-document step after the egress gate:

| Document | Action |
| --- | --- |
| `Deployment`, `StatefulSet` | `spec.replicas: 0` |
| `Job`, `CronJob` | `spec.suspend: true` |
| `HorizontalPodAutoscaler`, bare `Pod` | dropped |
| `Ingress` | Every `spec.rules[]` whose `host` equals `--hostname` (case-insensitive) has every `http.paths[].backend.service` replaced by `{name: <release>-caelus-parking, port: {number: <--parking-port>}}`. Annotations, middlewares and TLS are kept. |
| Added | One `Service` named `<release>-caelus-parking`, `type: ExternalName`, `externalName: <--parking-host>`, one port `<--parking-port>` |

**Rules:**
- **Untouched documents** pass through byte for byte, as today. PVCs, Secrets, ConfigMaps, the chart's Services, the tenant database and the bucket are untouched.
- **The chart's own router middlewares stay on the Ingress,** so app-auth still runs first. Only signed-in, allowed users reach the parking page of an auth-protected app, and scanners cannot.
- **Only the own hostname is rerouted.** Other hosts, such as App Studio's `preview-<app>-<handle>`, keep their backends and answer 503 through Traefik's empty-service behavior. App Studio's `preview-down` errors middleware, which catches 502–504, then serves its own page.
- **Why HPAs are dropped:** an HPA would scale the workload back to its minimum.
- **Reserved name.** `<release>-caelus-parking` is platform-reserved. Each deployment has its own namespace, so it cannot collide across deployments. The chart test asserts that no catalog chart renders a Service with that name.
- **The normal render is today's render.** It is the chart's output plus the egress gate, with the chart's own `replicas`, so Helm keeps owning `replicas` and every rollout converges it.
  - Stopped → normal: Helm applies the chart's 1 again.
  - Normal → stopped: Helm takes ownership of 0.
- **Alternative: rewrite the app's Service instead of the Ingress backends.** Rejected. Switching a Service between `ClusterIP` and `ExternalName` hits immutable fields, and the Service may also serve paths the Ingress does not route.
- **A host whose paths go to several Services** (Matrix, OpenProject, App Studio) just has every path point at the one ExternalName. The parking page proxies nothing, so nothing about the original backends needs recording.

### D5. Post-stop sweep

After every successful Helm apply in `stopped` mode, `provisioner.sweep_stopped_workloads(namespace)` runs:

```
kubectl get deployments,statefulsets -n <namespace> -o json
# for each item with spec.replicas > 0:
kubectl scale <kind>/<name> -n <namespace> --replicas=0
```

- **The guarantee.** A stopped deployment has no replicas, even if something outside Helm scaled a workload after Helm set 0.
- **Why it matters in the pause phase.** Sablier may scale a pausable workload up if a request reaches it while the stop is applied (appendix).
- **Why it can't be undone.** `kubectl scale` records no field owner, so Helm's ownership of 0 stands.
- **Failure.** A failure here fails the reconcile as a Helm failure does.

### D6. Helm hooks are banned; Vaultwarden invites its owner from a `postStart` hook

**The ban.** No catalog chart may render a document with a `helm.sh/hook` annotation. A chart test asserts it for every catalog chart. So nothing ever runs against a deployment at 0 replicas, and the stopped render needs no hook handling.

- **Alternative: drop hook documents in the stopped render.** Rejected. Only one chart has a hook. The pause phase also applies rollouts to deployments at 0 replicas, and in that case the post-renderer cannot know whether the app is up.

**Vaultwarden, chart 3.4.7 → 3.5.0.** The `post-install,post-upgrade` Job moves into a `postStart` hook on the `vaultwarden` container, following the precedent in Docmost (`products/docmost/chart/templates/docmost.yaml`) and immich-sso.

- **Delete** `templates/bootstrap-job.yaml`.
- **`templates/vaultwarden.yaml`:**
  - Add the env var `OWNER_EMAIL`: `{{ required "vaultwarden: caelus.owner.email is required to invite the first user" .Values.caelus.owner.email | quote }}`. The container already has `ADMIN_TOKEN` from the `<release>-admin` Secret.
  - Add the env var `READY_TIMEOUT`: `.Values.bootstrap.readyTimeoutSeconds`.
  - Add `lifecycle.postStart.exec.command: ["sh", "-eu", "-c", <script>]`. The script:
    1. Runs `exec >>/proc/1/fd/1 2>&1`, so its output reaches the container log; a `postStart` hook's own output is otherwise discarded. Both processes run as UID 1000.
    2. Polls `http://127.0.0.1:8080/alive` every second, the container port (`ROCKET_PORT=8080`), for up to `$READY_TIMEOUT` seconds. On timeout it prints the reason and exits 1.
    3. Creates a cookie jar with `mktemp -d` under `/tmp`, writable for UID 1000; the container has no read-only root. It POSTs the url-encoded `token=$ADMIN_TOKEN` to `/admin`. The admin API is cookie-authenticated; a bearer header does not work.
    4. POSTs `{"email":"$OWNER_EMAIL"}` to `/admin/invite`. A 2xx prints "invited $OWNER_EMAIL" and exits 0. A 409 prints "$OWNER_EMAIL already invited or registered; nothing to do" and exits 0.
    5. On any other status, GETs `/admin/users` and looks for the address. If it is there, it prints the Job's existing warning, that the email likely failed and the owner can register at `/#/register`, and exits 0. Otherwise it prints the status and body and exits 1.
  - Move the Job's explanatory comment block onto the hook.
- **`values.yaml` and `values.schema.json`:**
  - Remove `bootstrap.image`. The hook uses `/usr/bin/curl` from `vaultwarden/server:1.37.1`, verified present.
  - Keep `bootstrap.readyTimeoutSeconds` (default 120), its description now naming the hook.
- **`Chart.yaml`:** `version: 3.5.0`; `appVersion` unchanged.
- **`products/catalog/vaultwarden/vaultwarden.yaml`:** `template.chart_version: 3.5.0`.
- **`products/vaultwarden/README.md`:** describes the hook instead of the Job.

**Behavior:**
- **Failure restarts the container.** A non-zero exit makes the kubelet kill and restart the container, which retries, as in Docmost. On install or upgrade a persistent failure keeps the pod un-Ready, so `--wait` fails and the release rolls back: the same outcome as a failed Job.
- **Probes start only after `postStart` completes.**
- **It runs on every container start,** which after the first invite costs one admin login and a 409. The 120 s default stays well inside the 300 s Helm timeout.

### D7. The parking page is served by the API behind a host guard

There is no separate daemon. The stopped render's ExternalName points at the API Service of the same environment, and the API answers.

**The guard.** `ParkingGuard`, a pure ASGI middleware in `api/app/parking.py`, is added last in `api/app/main.py`, so it is the outermost layer and runs before CORS, `OriginGuard` and `ClientVersionGate`. For every `http` and `websocket` scope:
1. If `settings.domain` is empty (local development, and tests that do not set it), it passes the request through.
2. If `scope["client"]` is `127.0.0.1` or `::1`, it passes the request through. This lets operators use `kubectl port-forward` and `kubectl exec … curl localhost:8000`. Traefik always connects from its pod IP.
3. It lowercases the `Host` header and strips any port. If the host equals `settings.domain` lowercased, it passes the request through.
4. Otherwise it answers with the parking response and never calls the inner app, for every path and method.

Why the rules hold:
- **Why it is needed.** A tenant Ingress rerouted to the API bypasses the oauth2-proxy forward-auth that runs on the API's own Ingresses. Without the guard, anyone could send forged `X-Auth-Request-Email` and `X-Auth-Request-User` headers to a stopped app's hostname and reach every API route as anyone.
- **Why it is reliable.** The guarantee lives in the API and does not depend on the post-renderer: no future route can be exposed through a tenant hostname.
- **The loopback constraint.** uvicorn rewrites `scope["client"]` from `X-Forwarded-For` only for peers in `--forwarded-allow-ips`, which defaults to `127.0.0.1`. The API uses that default and must never widen it, or a visitor's `X-Forwarded-For: 127.0.0.1` could pass rule 2. A test asserts that a forwarded loopback address from a non-loopback peer gets the parking response.
- **Fail-safe if Traefik rewrote the Host.** If Traefik sent the ExternalName's FQDN as `Host` instead of the visitor's, the guard would still answer with the parking page; only the host named on it would be wrong. The dev rollout confirms the visitor's host arrives.
- **Future probes.** A probe added to the API pod later must send `Host: <settings.domain>`.

**The response.** Every caught `http` request gets `503` with `Cache-Control: no-store`.
- **Browser navigations** (method `GET`, `Accept` containing `text/html`, no `Upgrade` header) get the "stopped" page, rendered with `string.Template` from the standard library. The host goes through `html.escape`. The page copies the layout and styles of `products/custom/placeholder/index.html`, and reads "<host> is stopped."
- **Everything else** gets `text/plain; charset=utf-8` with "<host> is stopped.\n".
- **A caught `websocket` scope** is refused with `websocket.close` before accept, which uvicorn answers with HTTP 403.
- **It reads no database.** The pause phase leaves it unchanged; the payment phase adds a lookup by `lower(hostname)` for an "unavailable" page.

**Availability.** While the single API replica restarts, stopped apps answer Traefik's plain 503 instead of the branded page; the app is offline either way. Crawler traffic to stopped apps lands on API workers as a static response.

- **Alternative: a separate Go daemon** with its own image, module and namespace. Rejected. The page is stateless now and needs the database later, which the API already has, and a daemon would add an image release process for nothing.

### D8. Wiring

- **Terraform.** `tf/app/caelus/configmap.tf` sets `CAELUS_PARKING_HOST = "caelus-api.${var.namespace}.svc.cluster.local"` and `CAELUS_PARKING_PORT = "8000"` in the API and worker configmap. That resolves to `caelus-api.caelus.svc.cluster.local` in prod and `caelus-api.caelus-dev.svc.cluster.local` in dev.
- **Config.** `config.py` reads them as `parking_host: str = ""` and `parking_port: int = 8000`.
- **Provisioner.** `HelmAdapter.helm_upgrade_install` gains `render`, `release_name`, `parking_host` and `parking_port`, and passes the post-render flags. If `render == "stopped"` and `parking_host` is empty, it raises `IntegrityException` rather than render an Ingress that points nowhere.
- **No NetworkPolicy change.** `caelus-api-ingress` already admits Traefik on 8000.

### D9. Idempotence at the service, not the client

The stop and start service functions (`api/app/services/power.py`):
1. First take `SELECT … FOR UPDATE` on the deployment row. This keeps the invariant that every job creator writes the deployment row.
2. Return the current read without writing anything if the desired power already matches.
3. Otherwise check `status = ready` and, for start, that the desired row is `stopped` with reason `manual`.
4. Only then insert the power row, move `desired_power_id` and enqueue.

A `DeploymentInProgressException` at enqueue rolls the whole transaction back. Error codes are `deployment_not_ready` and `not_startable`, as `CodedException`s mapped to 409. The existing in-progress conflict is unchanged.

### D10. The read model gets a nested `power` object, from the database only

`DeploymentRead.power = {desired: "running"|"stopped", applied: "running"|"stopped", reason: str | None}`.
- Both pointer relationships are loaded with `lazy="joined"`, like the release pointers, so listing stays at one query.
- `reason` describes the desired row, and is null when the desired state is `running`.
- **Rule for this subsystem: no `DeploymentRead` field, single or listed, may need the Kubernetes API.** The pause phase serves its cluster-observed runtime status through separate routes.

### D11. CLI shape

`freepod stop` and `freepod start` follow `freepod delete`'s structure:
- the deployment comes from the project file;
- the environment check is the same;
- stop has no prompt;
- `--no-wait` is available;
- the wait polls `GET` until `power.applied == power.desired`, with `status = error` treated as failure, under `ROLLOUT_WAIT_SECONDS`.

`freepod deploy` checks `power.desired` on the settled read. If it is stopped, it prints that the deployment stays stopped and that `freepod start` runs it. It is a minor version bump. `MIN_CLIENT_VERSION` is not raised, because every change is additive.

### D12. Dashboard

- **Labels.** `ui/src/components/deployment/deploymentView.ts` derives the row label:

  | Condition | Label |
  | --- | --- |
  | `status` not `ready` | the existing labels |
  | desired `stopped`, applied `stopped` | Stopped |
  | desired `stopped`, applied `running` | Stopping, with progress |
  | desired `running`, applied `stopped` | Starting, with progress |
  | otherwise | the existing Running label |

- **Actions.**
  - **Stop** is offered when `ready` and desired `running`. It opens a confirmation dialog, extracted into its own component: the app stops running, its data is kept, visitors see a "stopped" page until it is started.
  - **Start** is offered when `ready` and desired `stopped` with reason `manual`, without confirmation.
  - Refusals show in the row.
- **Polling.** `ui/src/pages/Dashboard.tsx`'s `refetchInterval` also polls while any deployment's desired and applied power differ.

### D13. Routers without endpoints answer 503, already

A start restores the Ingress backends in the same Helm apply that scales the workloads up, before `--wait` sees them ready. Traefik keeps the router and answers 503 until the pods are ready, so visitors see the parking page, then Traefik's 503, then the app, never a 404.

- **No Terraform change.** This behavior is already live: chart 41.5.0 defaults `allowEmptyServices` to true.
- **A task verifies it** and adds a comment to `tf/deps/system/helm/traefik/values.yaml.tftpl` pinning the expectation.
- **Alternative: a two-phase start** (scale up, wait, then restore the Ingress). Rejected. A worker dying between the phases leaves a new state to recover: running, but unreachable.

### D14. Pausing goes to Sablier, not KEDA, Knative or an own idle loop

The pause phase delegates pausing when idle, and waking on traffic, to Sablier 1.19.1 with its Traefik plugin v1.4.0 (appendix).

| Approach | Verdict |
| --- | --- |
| KEDA HTTP add-on | Rejected. A beta proxy in front of all tenant traffic, and one scale target per object, while Freepod releases have several workloads. |
| Knative Serving | Rejected. Apps must be Knative Services, and third-party charts with StatefulSets cannot be. |
| An own daemon with an idle loop over Prometheus router counters, request tables and a compare-and-set on the latest job | Rejected. It needs guards against missing Prometheus data, cannot see long-lived connections (`traefik_open_connections` is per entrypoint only), and puts every pause and wake through a Helm reconcile. |
| Sablier | Chosen for the pause phase. Measured on dev, it adds about +0.7 ms at the median on a lightly loaded node and about +3 ms on a busy one. It keeps sessions alive across long-lived connections. |

It does not change this change. Sablier has no stopped state, so the power ledger, stop and start, the stopped render and the parking page are needed either way.

## Schema and queries

Every phase 1 statement was run against the schema on Nov 5, 2026 in a rolled-back transaction, with wider check constraints. Timestamps follow the existing schema: `timestamp` without time zone, holding UTC. Status literals are those in `api/app/services/reconcile_constants.py`.

### Schema additions

```sql
create table deployment_power (
    id            serial primary key,
    deployment_id uuid not null references deployment(id) on delete cascade,
    state         varchar not null check (state in ('running', 'stopped')),
    reason        varchar not null check (reason in ('manual', 'payment')),
    actor_user_id integer references "user"(id),  -- null: the platform
    created_at    timestamp not null,
    started_at    timestamp,                      -- reconciler, write-if-null
    ended_at      timestamp,                      -- reconciler, once
    error         text                            -- reconciler, once; null on success
);
create index ix_deployment_power_deployment on deployment_power (deployment_id, id);

alter table deployment
    add column desired_power_id integer references deployment_power(id),  -- null: running
    add column applied_power_id integer references deployment_power(id);  -- null: running
```

### Stop and start (one transaction each)

```sql
-- 1. Lock the deployment and read what the decision needs. `for update of d`:
--    Postgres cannot lock the nullable side of an outer join, and need not.
select d.status, coalesce(pw.state, 'running') as desired_state, pw.reason
from deployment d
left join deployment_power pw on pw.id = d.desired_power_id
where d.id = :deployment_id and d.user_id = :user_id
for update of d;
```

The service then decides, in this order:
1. **No row:** `404`.
2. **`desired_state` is already the target** (`stopped` for stop, `running` for start): return the read and write nothing.
3. **`status <> 'ready'`:** `409 deployment_not_ready`.
4. **Start, with `desired_state = 'stopped'` and `reason <> 'manual'`:** `409 not_startable`.

Otherwise:

```sql
-- 2. Record the intent.
insert into deployment_power (deployment_id, state, reason, actor_user_id, created_at)
values (:deployment_id, :target_state, 'manual', :actor_user_id, :now)  -- actor null via caelus
returning id;

-- 3. Move the desired pointer. The applied pointer belongs to the reconciler.
update deployment set desired_power_id = :power_id where id = :deployment_id;

-- 4. JobService.enqueue_job(reason='power'). A unique violation on
--    uq_open_reconcile_job_per_deployment raises DeploymentInProgressException:
--    roll the whole transaction back, so no power row remains, and answer 409.
```

### Reconciler

These run only when `desired_power_id is distinct from applied_power_id`.

```sql
-- Claim, committed before Helm runs, like _claim_desired_release.
update deployment_power set started_at = :now
where id = :desired_power_id and started_at is null;

-- Outcome, in the same transaction as the deployment's status.
update deployment_power set ended_at = :now, error = :error  -- error null on success
where id = :desired_power_id;

-- Success only.
update deployment set applied_power_id = desired_power_id where id = :deployment_id;

-- Failure only, in the same transaction as the outcome and status = 'error'.
-- --atomic restored the applied power, so the failed change is finished: the
-- desired pointer goes back to what is running, and the failed row is never
-- pointed at again.
update deployment set desired_power_id = applied_power_id where id = :deployment_id;
```

### Read model

```sql
select d.*,
       coalesce(dp.state, 'running') as power_desired,
       coalesce(ap.state, 'running') as power_applied,
       case when dp.state = 'stopped' then dp.reason end as power_reason
from deployment d
left join deployment_power dp on dp.id = d.desired_power_id
left join deployment_power ap on ap.id = d.applied_power_id;
```

### Vaultwarden prerequisite check

Run in each environment before the stop routes ship (Migration Plan, step 0). It must return no rows.

```sql
select d.id, d.namespace, dt.chart_version as desired, at.chart_version as applied
from deployment d
join product_template_version dt on dt.id = d.desired_template_id
left join product_template_version at on at.id = d.applied_template_id
join product p on p.id = dt.product_id
where p.slug = 'vaultwarden' and d.status <> 'deleted'
  and (dt.chart_version <> '3.5.0' or at.chart_version is distinct from '3.5.0');
```

## Risks / Trade-offs

- **[Risk] A rollout to a stopped deployment is recorded as succeeded without the new version booting.** → Accepted (D3). It surfaces at start as a failed reconcile with Helm's error and an atomic rollback.
- **[Risk] A stop of a Vaultwarden deployment still on chart 3.4.7 would run its `post-upgrade` hook against 0 replicas and roll back.** → Migration Plan step 0 moves every Vaultwarden deployment to 3.5.0 before the routes ship. The prerequisite query proves it.
- **[Risk] The API now answers on tenant hostnames.** → The host guard is outermost and catches every path, method and WebSocket. Its tests cover forged identity headers, a forwarded loopback address and the platform's own domain. The dev rollout repeats the forged-header check against a real stopped app.
- **[Risk] An API restart shows Traefik's plain 503 instead of the branded page for stopped apps.** → Accepted; the app is offline either way.
- **[Risk] A failed power reconcile sets `status = error` while the app may be fine after the rollback.** → Consistent with failed rollouts. It also exempts the deployment from further power changes until the owner redeploys.
- **[Risk] Every Vaultwarden container start makes an admin call.** → Idempotent: a 409 after the first invite. It costs one login and one request per start.
- **[Trade-off] The parking page names the hostname, not the product.** → The payment phase adds the database lookup that can name the product.
- **[Risk] Service name collisions.** → `<release>-caelus-parking` is reserved, and the chart test asserts no catalog chart renders it.

## Migration Plan

0. **Vaultwarden first.**
   1. Merge the chart rewrite (D6). CI publishes chart 3.5.0 on merge; a hand push for pre-merge testing must never reuse a published version.
   2. `caelus catalog apply` creates the new template version.
   3. In each environment, inside the API pod, run `caelus update-deployment --desired-template-id <new>` for every Vaultwarden deployment.
   4. Run the prerequisite query until it returns no rows.
   5. On dev, confirm a fresh Vaultwarden deployment's owner receives the invitation and the container log shows the hook's line, and that a restart logs "already invited or registered".
1. **Merge** the rest with the Alembic migration. Existing deployments read as running, and every render is `normal`.
2. **Apply `tf/app` on dev** with the new API image. This sets `CAELUS_PARKING_HOST` and `CAELUS_PARKING_PORT`.
3. **Verify on dev:**
   - `--providers.kubernetesingress.allowEmptyServices=true` is in the live Traefik's arguments;
   - stop and start a `custom` deployment: the hostname serves the 503 stopped page, then Traefik's 503, then the app, never a 404;
   - stop and start Vaultwarden: no hook runs, and on start the `postStart` invite answers 409;
   - stop Matrix: every path of the multi-backend host serves the stopped page;
   - stop App Studio: the preview host keeps its backend and answers 503;
   - deploy to a stopped deployment: it stays stopped;
   - the page names the app's host, not `caelus-api…`, which shows the visitor's `Host` arrives through the ExternalName;
   - `curl -H 'X-Auth-Request-Email: <someone>' https://<stopped-app-host>/api/users/me` gets the parking 503, not an API response;
   - `curl -H 'X-Forwarded-For: 127.0.0.1' -H 'X-Auth-Request-Email: <someone>' https://<stopped-app-host>/api/users/me` also gets the parking 503;
   - `kubectl -n caelus-dev port-forward deploy/caelus-api 8000` followed by `curl localhost:8000/api/...` reaches the API;
   - while stopped, `kubectl get … --show-managed-fields` shows Helm owns `replicas: 0`; after start, replicas are 1.
4. **Apply `tf/app` on prod,** then release `freepod` with a `freepod-v*` tag.

**Rollback:** start every stopped deployment (`caelus start-deployment`), then revert the API image. Stopped deployments otherwise render normally on their next reconcile, and stay stopped only until something reconciles them. The Vaultwarden 3.5.0 chart stays; it works without this change.

## Appendix: the pause phase, and what it needs from this change

The next change adds **pause when idle**. This appendix is the summary it builds on, kept here so that the repository states the whole subsystem. Phase 1 is built so that none of it needs rework.

**Mechanism.**
- **Sablier** 1.19.1 is a cluster singleton in `tf/deps/system/sablier.tf`. Groups are keyed by deployment namespace.
- **Traefik loads the Sablier plugin.** v1.4.0 is vendored in the repository as an `inlinePlugin`, with a Freepod patch that:
  - answers non-browser requests with 503 and `Retry-After`;
  - fails open on Sablier error responses;
  - adds a request timeout.
- **Wake and pause.** A pausable deployment's workloads carry `sablierapp.dev/enable: "true"` and `sablierapp.dev/group: <namespace>`. Its Ingresses get a per-release Sablier Middleware appended last, after app-auth. Sablier scales the group to 0 after an hour without requests, and back to 1 on the next request, showing a branded waiting page meanwhile.
- **Long-lived connections** keep the session alive through `keepAliveInterval`.

**What the pause phase needs from phase 1:**
- **A third render mode.** `--render` gains `pausable`: replicas stripped so Sablier owns the field, Sablier labels added, the Middleware added and appended to every Ingress.
  - Every mode removes chart-set `sablierapp.dev/enable` and `group` (and the legacy `sablier.*` forms), so normal and stopped renders never put a workload under Sablier.
  - Charts may set `sablierapp.dev/ready-after`, `ready-on-start`, `running-hours` and `running-days`.
- **The stopped render must keep setting `replicas: 0`,** so Helm owns 0. Stopped → pausable then removes the field and it defaults to 1 (measured on dev), and Sablier adopts the running app. The normal render must keep the chart's `replicas`, so Helm owns 1.
- **The post-stop sweep (D5)** covers a request that reaches Sablier while a stop is applied.
- **No hooks (D6).** A rollout to a paused deployment is applied at 0 replicas and recorded as succeeded, and it boots on the next visit. With no hooks, nothing runs against it.
- **Deployment reads stay database-only (D10).** The cluster-observed runtime status (paused, starting, pausing, running) gets its own routes.
- **The parking page serves only stopped apps.** Paused apps get Sablier's waiting page instead.
- **The ledger stays two-state.** Pausing is a running deployment's property, decided by the chart value `pause.whenIdle`, declared in every chart's schema. Each product's template exposes it or not, with the product's default in `system_values`. No ledger state or reason is added.
