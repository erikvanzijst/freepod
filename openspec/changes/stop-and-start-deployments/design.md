# Design

## Context

This change is phase 1 of a subsystem that later adds pausing, starting on traffic, idle pause and stopping for payment. What those phases need from this one is in the appendix, Later phases. Three facts about today's code shape it.

- **Every reconcile is a rollout.** `DeploymentReconciler.reconcile` always claims the desired release (`_claim_desired_release`) and records its outcome (`_record_release_outcome`). The release ledger forbids rewriting those columns (`deployment-release-ledger`, "No release column is revised after it is written"). Today that never conflicts, because the only reconciles are create, update and delete, and each comes with a new release.
- **The post-renderer already sees everything.** `api/app/post_render.py` runs on every `helm upgrade` as a Helm 4 plugin. Under Helm 4.3 it also receives hook documents: rendering Vaultwarden through it puts the egress gate into the `post-upgrade` bootstrap Job.
- **Traefik drops routers without endpoints.** The Kubernetes Ingress provider omits a router whose Service has no endpoints, and the request gets a 404. `allowEmptyServices: true` keeps the router, runs its middlewares and answers 503 (Traefik reference, `providers.kubernetesIngress.allowEmptyServices`). Traefik 3.7.13 runs as a single replica configured in `tf/deps/system/helm/traefik/values.yaml.tftpl`, shared by dev and prod.

## Goals / Non-Goals

**Goals:**

- Owners can stop and start a deployment, keeping all of its data. The API, `caelus`, `freepod` and the dashboard all support it.
- Build the parts later phases reuse unchanged:
  - the power ledger and its pointers;
  - the reconciler's power branch;
  - the post-renderer's suspended render;
  - the 503 behavior at the edge;
  - the activator as a deployed daemon.
- Prove that a stopped release survives Helm's three-way merge across later upgrades.

**Non-Goals:**

- Pausing, starting on traffic and the "starting up" page (phase 2).
- Idle detection, the request tables, the activator's database role and Prometheus access, and `initiated_by_user_id` (phases 2 and 3).
- Stopping for payment arrears (phase 4). Start already refuses `payment` stops, so that rule needs no later change.
- Capacity policy for nodes that cannot hold every deployment running.

## Decisions

### D0. One vocabulary on every surface

There are three actions: **stop**, **pause** and **start**. Their states are **stopped**, **paused** and **running**. A stopped app never starts on its own; a paused app starts on its next visitor's request; start runs either. These are the only words used in the dashboard, the API (routes, state values, error codes), `caelus`, `freepod` and the docs.

| Action | Resulting state | Meaning |
| --- | --- | --- |
| **Stop** | `stopped` | Nothing runs. Only an explicit start runs it again. |
| **Pause** | `paused` | Nothing runs. A visitor's request starts it. |
| **Start** | `running` | Runs again, whether it was stopped or paused. |

- **Stop and start are the familiar pair** (Docker, EC2, systemd). Start also reads correctly after a pause.
- **Not resume.** "Resume" implies carrying on where something left off, which is wrong after a deliberate stop.
- **Not suspend.** "Suspend" means different things elsewhere: Docker's `pause` freezes processes, Fly's `suspend` snapshots memory, Render's suspended service never wakes. It would blur the one distinction that matters, whether traffic starts the app.

"Suspended" survives only inside the platform, as the name of the render in which nothing runs, which paused and stopped deployments share (`--suspended`, "a suspended render"). No route, field, label or message exposes it.

### D1. Power is a ledger beside the release ledger, not inside it

`deployment_power` rows hold intent (`state`: `running` | `paused` | `stopped`; `reason`; actor; `created_at`) and outcome (`started_at`, `ended_at`, `error`). `deployment.desired_power_id` and `deployment.applied_power_id` point into it, and null means `running`. The DDL is in Schema and queries, below.

The state carries the whole meaning, with no separate wake-on-traffic flag. Paused is exactly "a request starts it", and stopped is exactly "only start runs it". The reason records why: `manual` (an owner, admin or operator action, in either direction), `idle` (paused by the idle sweep), `payment` (stopped for arrears), `traffic` (started by a visitor's request) and `release` (started by an owner deploy).

- **Alternative: a new release per power change.** Rejected. A daily idle app would add two releases a day to `freepod releases`, and image retention, which walks releases, would see churn that has nothing to do with deploys.
- **Alternative: enum columns on `deployment`.** Rejected. The UI, the activator and later phases need the reason, actor and outcome of the latest change, and a ledger keeps their history for free.

Unlike the release pointers, the power pointers are nullable. So the circular foreign key needs no `DEFERRABLE` treatment: insert the row, then move the pointer. It also needs no backfill.

### D2. Power changes require `status = ready`

This rule makes the reconciler branch cheap. Only a successful reconcile sets `ready`, and it sets `applied_release_id` in the same transaction, so when a deployment is `ready` its desired release is its applied release. A power-only reconcile therefore re-renders exactly what is running, normally or suspended. Nothing has to reconstruct values from the applied release's snapshot. A deployment in `error` is in a state nobody fully knows, so the platform does not apply power changes to it at all.

The power service functions do not change `status`, which keeps describing the provisioning lifecycle: a stopped or paused deployment is still `ready`, which leaves the validated transition table in `deployment-payment-states` untouched. A stop in flight is "`ready`, desired ≠ applied power", which is how the UI tells Stopping from Stopped and Starting from Running. A stopped deployment that a failed platform rollout turns to `error` is recovered by the owner deploying, which fixes it and leaves it stopped, and then starting it. `update_deployment` racing a power change still gets the existing 409, from `uq_open_reconcile_job_per_deployment` at enqueue.

### D3. The reconciler stays level-triggered: rollout iff `applied_release_id ≠ desired_release_id`

`reconcile()` decides from the pointers, not from the job's reason:

```python
release = deployment.desired_release
rollout = deployment.applied_release_id != release.id
if rollout:
    self._claim_desired_release(deployment)
power = deployment.desired_power            # None means running
claim_power(power)                          # started_at, write-if-null
...helm_upgrade_install(..., suspended=power is not None and power.state != "running")
on success:  applied_release_id = release.id (if rollout); applied_power_id = desired_power_id;
             power.ended_at = now
on failure:  status = error, last_error; power.ended_at, power.error;
             release outcome only if rollout
```

`_reconcile_apply` keeps using `release` for the vars Secret and the release overrides. When `rollout` is false, that release is the applied one. A lease reclaim of a rollout still sees `applied ≠ desired` and claims it again, write-if-null as today. The power service functions enqueue jobs with a new reason, `power`, which is informational only, because the reconciler never branches on the reason. The worker needs no change: a failed power reconcile returns `status = error`, and the worker marks the job failed.

The power row's outcome is recorded only when `desired_power_id` is set and differs from `applied_power_id`. A rollout to a deployment that is already stopped therefore leaves the power row's end time as it was.

### D4. The suspended render is one more post-render step

`post_render.py` gains `--suspended`, `--release` and `--activator-host`. With `--suspended`, `render()` runs a per-document step after the egress gate:

| Document | Action |
| --- | --- |
| Any document with a `helm.sh/hook` annotation | Dropped |
| `Deployment`, `StatefulSet` | `spec.replicas: 0` |
| `Job`, `CronJob` | `spec.suspend: true` |
| `HorizontalPodAutoscaler`, `Pod` | Dropped |
| `Ingress` | Every `spec.rules[]` whose `host` equals `--hostname` (case-insensitive) has every `http.paths[].backend.service` replaced with `{name: <release>-caelus-activator, port: {number: 80}}` |

The step also appends one `ExternalName` Service: `<release>-caelus-activator`, `externalName: <--activator-host>`, port 80. Helm passes no release name to post-renderers, which is why the reconciler passes `--release=<name>`.

- **Alternative: rewrite the app's Service instead of the Ingress backends.** Rejected. Changing a Service between `ClusterIP` and `ExternalName` hits immutable fields, and the Service may be shared by paths the Ingress does not route.
- Because the activator proxies nothing, nothing about the original backend needs to be recorded. A host whose paths go to several Services (Matrix, OpenProject, App Studio) just has every path point at the one ExternalName.

An HPA is dropped because it would scale the workload back to its minimum. No catalog chart renders an HPA, a CronJob or a bare Pod today; those steps are there for the charts that will.

The chart's own router middlewares stay on the Ingress, so app-auth still runs first: only signed-in, allowed users reach the activator of an auth-protected app, and scanners cannot. PVCs, Secrets, the tenant database and the bucket are untouched.

Documents the step does not touch pass through byte for byte, as today.

### D5. `allowEmptyServices: true` on the Kubernetes Ingress provider

Helm applies every manifest before `--wait` watches for readiness. So a start restores the Ingress backends while the pods are still booting, and without this setting visitors would see 404s until they are ready. With it, the sequence is a 503 from the activator, then a 503 from Traefik, then the app, from a single Helm apply.

- **Alternative: a two-phase start (scale up, wait, then restore the Ingress).** Rejected. A worker dying between the phases leaves a new state to recover: running, but unreachable.
- **Alternative: an `errors` middleware.** Rejected. It would replace the app's own 503 responses as well.

This is set in `tf/deps` (a cluster singleton). It takes effect for every Ingress in dev and prod, and applying it restarts Traefik.

### D6. The phase-1 activator is stateless

`daemons/activator/` is a Go `net/http` server, built into the shared daemons image.

- **Serving port 8080:** every request gets a 503 with `Cache-Control: no-store`. Requests that accept `text/html` get the "stopped" page, built with `html/template` from a copy of `products/custom/placeholder/index.html`'s layout and naming the request's host. All others get `text/plain`. WebSocket upgrades get a plain 503.
- **Health port 8081:** `/healthz` only.

It reads no database. Phase 2 adds the database role, the "starting up" page for paused apps and start requests, and the page copy then comes from the deployment's row. Stateless now means phase 1 creates no credential, grant or network path that phase 2 would have to revisit.

- **Alternative: reuse app-auth's process.** Rejected. app-auth runs as one replica and owns authentication, while the activator answers for every app that is not running and should fail on its own.

### D7. Activator deployment mirrors app-auth's

`tf/app/activator/` is a module instantiated once per workspace. It creates:

- a namespace (`activator`, or `activator-dev` in dev);
- a Deployment with 2 replicas and `command = ["/activator"]`, pinned through `activator_image` in `tf/app/variables.tf`;
- a Service on port 80 targeting 8080;
- a NetworkPolicy admitting only `kube-system`/`app.kubernetes.io/name=traefik` on 8080, and the kubelet on 8081.

The module outputs the Service's FQDN. `tf/app/caelus` passes it into the configmap as `CAELUS_ACTIVATOR_HOST`, read by `config.py` as `activator_host` and handed to the post-renderer by `HelmAdapter`. If the setting is empty, the reconciler refuses to render a suspended release (`IntegrityException`) rather than render an Ingress that points nowhere.

### D8. Idempotence at the service, not the client

The stop and start service functions first take `SELECT … FOR UPDATE` on the deployment row. That keeps the invariant that every job creator writes the deployment row, which phase 3's compare-and-set relies on (appendix, Later phases). They then return the current read without writing anything if the desired power already matches. Otherwise they check `status = ready`, and for start that the deployment is paused or stopped with reason `manual`. Only then do they insert the power row, move `desired_power_id` and enqueue. A `DeploymentInProgressException` at enqueue rolls the whole transaction back.

Error codes: `deployment_not_ready` and `not_startable`, as `CodedException`s mapped to 409. The existing in-progress conflict is unchanged.

### D9. The read model gets a nested `power` object

`DeploymentRead.power = {desired: "running"|"paused"|"stopped", applied: "running"|"paused"|"stopped", reason: str | None}`. Both pointer relationships are loaded with `lazy="joined"`, like the release pointers, so listing stays at one query. `reason` describes the desired row, and is null when the desired state is `running`.

### D10. CLI shape

`freepod stop` and `freepod start` follow `freepod delete`'s structure:
- the deployment comes from the project file;
- the environment check is the same;
- `--no-wait` is available;
- the wait polls `GET` until `power.applied == power.desired`, with `status = error` treated as failure, under `ROLLOUT_WAIT_SECONDS`.

`freepod deploy` checks `power.desired` on the settled read and prints the stopped notice. It is a minor version bump. `MIN_CLIENT_VERSION` is not raised, because every change is additive.

### D11. An own activator and the post-renderer, not KEDA, Knative or Sablier

An own activator wins because the off-the-shelf options all assume one scalable workload per app, while Freepod releases are arbitrary Helm charts with several Deployments and StatefulSets.

| Approach | Data path while running | Several workloads per app | Fights Helm over replicas | Verdict |
| --- | --- | --- | --- | --- |
| KEDA HTTP add-on | Every request passes its interceptor proxy | No: one `scaleTargetRef` per HTTPScaledObject | Yes, via the HPA it creates | Reject. Puts a beta proxy in front of all tenant traffic and only scales one workload. |
| Knative Serving | Activator only when cold | No: apps must be Knative Services | n/a | Reject. Third-party charts with StatefulSets cannot be rewritten as Knative Services. |
| Sablier (Traefik plugin) | Every request calls the Sablier server to refresh its session | Yes, via group labels | Yes, scales outside Helm | Close, but makes Sablier a single point of failure for every app, needs Traefik's Yaegi plugin loader, and restores to a fixed replica count. |
| Own activator + post-renderer (recommended) | Untouched: running apps route straight to their pods | Yes: the post-renderer rewrites every workload in the release | No: the power state is part of the Helm release | Build. Small Go daemon that serves pages and runs the idle loop, a post-render step, one housekeeping tick and API/CLI/UI. |

The key property of the recommendation is that a running app has zero added hops. The activator is only in the path while an app is paused or stopped, and it never proxies, so an activator outage can never take down a running app.

## Schema and queries

Every statement in this section was run against the current schema (Nov 5, 2026) in a rolled-back transaction. Timestamps follow the existing schema: `timestamp` without time zone, holding UTC. Status literals are those in `api/app/services/reconcile_constants.py`.

### Schema additions

```sql
create table deployment_power (
    id            serial primary key,
    deployment_id uuid not null references deployment(id) on delete cascade,
    state         varchar not null check (state in ('running', 'paused', 'stopped')),
    reason        varchar not null
                  check (reason in ('manual', 'idle', 'payment', 'traffic', 'release')),
    actor_user_id integer references "user"(id),  -- null: the platform; plain FK, as deployment_var's
    created_at    timestamp not null,
    started_at    timestamp,                      -- written by the reconciler, once each
    ended_at      timestamp,
    error         text
);
create index ix_deployment_power_deployment on deployment_power (deployment_id, id);

alter table deployment
    add column desired_power_id integer references deployment_power(id),  -- null: running
    add column applied_power_id integer references deployment_power(id);  -- null: running
```

The pointers are nullable, so the circular reference needs no deferred constraint: a power change inserts its row, then moves `desired_power_id`. Deleting a deployment row cascades to its power rows in the same statement; the pointers that reference them disappear with the row.

### Stop and start (one transaction each)

```sql
-- 1. Lock the deployment and read what the decision needs. `for update of d`:
--    Postgres cannot lock the nullable side of an outer join, and does not need to.
select d.status, coalesce(pw.state, 'running') as desired_state, pw.reason
from deployment d
left join deployment_power pw on pw.id = d.desired_power_id
where d.id = :deployment_id and d.user_id = :user_id
for update of d;
```

The service then decides, in this order:
1. **No row:** `404`.
2. **`desired_state` is already the target** (`stopped` for stop, `running` for start): return the read, write nothing.
3. **`status <> 'ready'`:** `409 deployment_not_ready`.
4. **Start, and `desired_state = 'stopped'` with `reason <> 'manual'`:** `409 not_startable`.

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

Only when `desired_power_id is distinct from applied_power_id`. A rollout to a deployment whose power is already applied writes no power row.

```sql
-- Claim, committed before Helm runs, like _claim_desired_release; write-if-null
-- so a lease reclaim keeps the first start time.
update deployment_power set started_at = :now
where id = :desired_power_id and started_at is null;

-- Outcome, in the same transaction as the deployment's status.
update deployment_power set ended_at = :now, error = :error  -- error null on success
where id = :desired_power_id;

-- Success only. On failure applied_power_id is left alone: --atomic restored it.
update deployment set applied_power_id = desired_power_id where id = :deployment_id;
```

The suspended render is chosen from the same row: `--suspended` when the desired power row exists and its `state <> 'running'`.

### Read model

Both pointers are joined relationships, so listing deployments stays one query. Its shape:

```sql
select d.*,
       coalesce(dp.state, 'running') as power_desired,
       coalesce(ap.state, 'running') as power_applied,
       case when dp.state is distinct from 'running' then dp.reason end as power_reason
from deployment d
left join deployment_power dp on dp.id = d.desired_power_id
left join deployment_power ap on ap.id = d.applied_power_id;
```

## Risks / Trade-offs

- **[Risk] `allowEmptyServices` changes 404 to 503 for every Ingress without ready endpoints, in both environments.** → It is the more accurate status, and nothing in the repo relies on the 404. Check App Studio's `preview-down` errors middleware (catches 502–504) on dev after the change: with the studio down, its errors service has no endpoints either, so a plain 503 is the expected result.
- **[Risk] A rollout to a stopped deployment is recorded as succeeded without the new version ever booting.** → Accepted: the alternative, starting every stopped and paused deployment on every rollout, would be a fleet-wide start storm. It surfaces at start as a failed reconcile with Helm's error.
- **[Risk] A Helm wait with 0 replicas passes trivially, so a broken chart change on a stopped deployment is invisible until start.** → Same as above.
- **[Risk] Dropping hooks skips migration hooks on releases applied while stopped.** → Hooks run on the next normal render, which is the start. They run against the new version on first boot, exactly as on any upgrade.
- **[Risk] A failed power reconcile sets `status = error` while the app may be running fine after the rollback.** → Consistent with failed rollouts, and it exempts the deployment from further power changes until the owner redeploys. Phase 3's sweep relies on that exemption.
- **[Trade-off] The phase-1 page names the hostname, not the app.** → Phase 2's database lookup replaces it with the product name.
- **[Risk] Service name collisions.** → `uq_deployment_namespace` gives each deployment its own namespace, so `<release>-caelus-activator` cannot collide across deployments. A chart rendering a Service with that exact name would collide, so the suffix is a platform-reserved name. The post-renderer test asserts it against every catalog chart.

## Migration Plan

1. Merge with the Alembic migration. Existing deployments read as running (null pointers), and the post-renderer renders all of them normally.
2. Bump `daemons/VERSION`. CI publishes the image; then set `activator_image` and apply `tf/app` on dev. This creates the activator and sets `CAELUS_ACTIVATOR_HOST`.
3. Apply `tf/deps` with `allowEmptyServices`, which restarts Traefik (shared).
4. On dev, in the first experiment:
   - stop and start a `custom` deployment;
   - stop a Vaultwarden deployment (hook drop);
   - stop a Matrix deployment (multi-backend host);
   - update a stopped deployment and confirm it stays stopped.
5. Apply `tf/app` on prod, then release `freepod` with a `freepod-v*` tag.

Rollback: revert the API image. Stopped deployments then render normally on their next reconcile, and stay stopped only until something reconciles them. Before rolling back, start every stopped deployment (`caelus start-deployment`). `allowEmptyServices` can stay; it is harmless without stopped deployments.

## Appendix: Later phases

This appendix is the design for the phases after this change, kept here so that the repository holds the whole subsystem. Later changes take their requirements from it; phase 1 is built so that none of it needs rework.

### Platform pieces it builds on

Five existing pieces carry most of the work, so this is mostly new glue rather than new infrastructure.

| Piece | Where | What it gives this feature |
| --- | --- | --- |
| Helm post-renderer | `api/app/post_render.py`, passed on every `helm upgrade` in `api/app/provisioner.py` | A place to rewrite every chart's rendered manifests without touching 14 product charts. It already injects the egress gate into every pod template. Under Helm 4 it also receives hook documents. |
| Traefik router metrics | `metrics.prometheus.addRoutersLabels: true` in `tf/deps/system/helm/traefik/values.yaml.tftpl` | `traefik_router_requests_total{router=...}` per router. Routers are named `<namespace>-<release>-...@kubernetes`, the same mapping `api/app/services/http_logs.py` already relies on. |
| Housekeeping worker | `api/app/db_worker.py` | Independent ticks, each on its own cadence, each isolated from the others' failures. Home of the tick that turns the activator's start and pause requests into power changes. |
| Go edge daemons | `daemons/` (app-auth, ssh-auth) | A ready pattern and image for a new `activator` daemon, including Postgres roles that grant only the columns a daemon needs. |
| Reconcile queue | `caelus worker`, `api/app/services/reconcile.py` | The single writer of cluster state. Every power change is a reconcile. `uq_open_reconcile_job_per_deployment` allows one open job per deployment. |

Two things are not there yet. Traefik drops the router of an Ingress whose Service has no endpoints and answers 404, unless `allowEmptyServices` is set, in which case it keeps the router and answers 503. And a plain `kubectl scale` would be undone by the next `helm upgrade`, because Helm's three-way merge restores `replicas` from the chart.

### Starting on traffic and idle pause

**One daemon, both halves.** Starting on traffic and pausing when idle are two halves of one feature, so they ship as one Go daemon under `daemons/`, the activator.
- **Request path:** maps the request's Host to a deployment, answers with the right page or text, and files a start request when one can be honored. It holds no requests and proxies nothing, which rules out a pile-up of held connections and leaves it nothing to know about a chart's backends.
- **Idle loop:** queries Prometheus and files pause requests (Idle detection, below).
- **Access:** its Postgres role follows the ssh-auth and app-auth precedent, with SELECT on only the columns its queries read and INSERT on the two request tables (the grants are in Later schema additions). It reads Prometheus over HTTP, and has no Kubernetes access and no route to the API.
- **Replicas:** two, because it answers for every app that is not running. Both run the idle loop, which is harmless because the request tables deduplicate and the consumer re-checks.

**Power requests.** The daemon never changes power itself. It files intent rows in two tables, and one tick in the housekeeping worker (`caelus-db-worker`) turns them into power changes. The tick calls the same service functions the owner's Pause and Start use. The tables are in Later schema additions and every statement in Later queries.

The tables hold only open requests; the history lives in `deployment_power` as `traffic` and `idle` rows. The contract:

1. **The activator** files a request only when it can be honored. It writes with `INSERT … ON CONFLICT DO NOTHING`, so the primary key keeps at most one open request per deployment and table without a read first, and two replicas cannot race. Postgres requires only the INSERT privilege for `DO NOTHING`.
   - A start request when the deployment is `ready` and its desired power is `paused`.
   - A pause request when the idle loop finds the deployment idle (below), carrying the `id` of the latest reconcile job it read alongside the evidence.
2. **The power-request tick** (a cadence of a couple of seconds) selects requests `FOR UPDATE SKIP LOCKED` and handles each in one transaction.
   - **Start, done or not eligible:** deleted. Done means a `traffic` power row was written and a reconcile enqueued. Not eligible means stopped, not `ready`, or already running.
   - **Start, blocked:** with a reconcile already open (`DeploymentInProgressException`, for example a pause still being applied), the request is kept and the next tick retries.
   - **Pause:** the tick locks the deployment row and pauses (an `idle` power row with state `paused`, a reconcile enqueued) only if all of these hold:
     - the latest reconcile job is still `expected_job_id` and `done`;
     - the deployment is still `ready` and running;
     - `pause_when_idle` is still on.

     The exact statements are in Later queries. Either way the request is deleted: a stale request is not retried, because the next idle sweep re-evaluates from fresh evidence.

The service functions enforce eligibility regardless of what the activator checked. The activator checks too, so it never files a request it knows cannot be honored. A faulty activator can do no more than start a paused app, which any anonymous visitor can, or pause a running app that has idle pause on, which the next visit starts again. The foreign key check on insert runs with the table owner's rights, so the INSERT grant is all the activator needs. That, the deduplication on conflict, and the column grants covering both activator queries were verified against the current schema on Nov 5, 2026, running as the role.

**No rate limiting.** The primary key collapses any number of visits into one open request, and the service function into one reconcile. A sweep that starts many apps at once is bounded by the reconcile worker pool's concurrency and by the scheduler, which leaves pods pending rather than overcommitting nodes. Add a limit only if spurious starts show up as a real cost.

**Idle detection.** The activator's idle loop runs every few minutes. One Prometheus query covers all routers; Traefik is scraped by two jobs (`kubernetes-pods` and `kubernetes-service-endpoints`), so the queries pin one:

```promql
sum by (router) (increase(traefik_router_requests_total{job="kubernetes-pods"}[1h]))
```

Router prefixes map to deployments exactly as in `http_logs.py`. A deployment is idle when its routers saw zero requests over the window (one caelus setting, default 1 hour). The window counts from the latest of: its last request, a build, an owner-initiated release, and its latest `running` power row (a start). Two guards keep missing data from reading as idleness:

- **Coverage.** Nothing is paused unless Traefik has been up and continuously scraped for the whole window. This also covers Prometheus having been down, which leaves gaps in `up`:

  ```promql
  min(time() - process_start_time_seconds{job="kubernetes-pods",app_kubernetes_io_name="traefik"}) > 3600
  and min(count_over_time(up{job="kubernetes-pods",app_kubernetes_io_name="traefik"}[1h])) >= 57
  and min(min_over_time(up{job="kubernetes-pods",app_kubernetes_io_name="traefik"}[1h])) == 1
  ```

  (57 of the 60 samples a 60 s scrape interval yields per hour.) If Prometheus does not answer, nothing is paused either.
- **Young series.** `increase()` cannot count a series' first sample, so a router whose first requests since Traefik started all landed in one scrape would read as zero. A router whose series is younger than the window (`count_over_time(...[1h]) < 57`) counts as active.

Only deployments that are not in flight (Later queries defines it precisely), have a hostname, have `pause_when_idle` on and are currently running are candidates. A failed latest job exempts the deployment, for the same reason power changes require `ready`. SSH is ignored: only the owner connects over SSH and can start the deployment themselves, so a session open at pause time is simply cut off. Idle always pauses, never stops.

Traefik records a request when it completes, so a WebSocket or SSE stream counts once, when it closes, and Traefik 3.7 has no per-router open-connections gauge (only `traefik_open_connections` per entrypoint). A client holding one long-lived stream and making no other requests looks idle. The sweep deliberately has no app-specific knowledge, so App Studio, whose UI watches the agent over SSE, can be paused with a tab open. That is an accepted limitation of the first version.

**The race, closed by compare-and-set.** Between the idle loop's decision and the tick acting on it, the owner may deploy or someone may start the app. So the loop reads the deployment's latest reconcile job in the same query that feeds the decision and files its `id` as `expected_job_id`. The tick pauses only if that is still the latest job and it is `done` (Power requests, above).
- **Why it works:** every state change creates a reconcile job (deploy, edit, var change, stop, pause, start, platform rollout), and `uq_open_reconcile_job_per_deployment` allows only one open job per deployment. The comparator is the integer primary key, not `created_at`, so it cannot tie.
- **What it misses:** a request that reaches the app in the seconds between decision and pause creates no job and is not caught. The app is paused, and the next request starts it.
- **Builds:** a build does not create a job, but it runs in the builds namespace, not in the app, and counts toward the countdown through its own timestamp.

**Who initiated a release.** The countdown restarts on owner releases but not on platform rollouts, so each release records who started it: `initiated_by_user_id` on `deployment_release`, null for releases the platform runs on its own. `update_deployment` gains a keyword-only `actor: UserORM | None` argument without a default, so every caller has to decide:
- the API route passes `current_user`;
- the `caelus` CLI passes `None` (the platform);
- `create_deployment` records the creator.

An owner release is one whose actor is the deployment's owner; an administrator moving a deployment to a new template counts as platform. The reconciler never creates releases, so nothing is copied from the transient job. The column answers who was responsible for any release, not only this feature.

**Releases on a stopped or paused deployment.** Platform rollouts, such as a catalog chart upgrade rolled out to every deployment, neither restart the countdown nor start anything: a deployment that is not running is re-rendered suspended, so a fleet-wide upgrade causes no start storm. An owner release on a paused deployment starts it (a `release` power row in the same transaction as the release), since the owner expects to see the result. An owner release on a stopped deployment leaves it stopped, and the CLI says so and points at `freepod start`.

A rollout applied to a stopped or paused deployment is recorded as succeeded without the new version ever having booted; a broken upgrade surfaces at the next start, as a failed start. That is preferred over starting every deployment on every rollout.

### Later schema additions

Phase 1 creates `deployment_power` and its pointers (Schema and queries, above). Phases 2 and 3 add the rest. These statements and the queries that follow were run against the current schema (Nov 5, 2026) in a rolled-back transaction, with the inserts and the activator's queries executed as the `activator` role holding only these grants.

```sql
alter table deployment
    add column pause_when_idle boolean not null default false;              -- phase 3

alter table deployment_release
    add column initiated_by_user_id integer references "user"(id);         -- phase 3; null: the platform

-- "Latest reconcile job" is read per deployment by every query below (phase 3).
create index ix_deployment_reconcile_job_latest on deployment_reconcile_job (deployment_id, id);

create table deployment_start_request (                                   -- phase 2
    deployment_id uuid primary key references deployment(id) on delete cascade,
    requested_at  timestamp not null default (now() at time zone 'utc')
);
create table deployment_pause_request (                                   -- phase 3
    deployment_id   uuid primary key references deployment(id) on delete cascade,
    expected_job_id integer not null,
    requested_at    timestamp not null default (now() at time zone 'utc')
);
grant insert on deployment_start_request, deployment_pause_request to activator;

-- Exactly the columns the activator's queries below read.
grant select (id, hostname, status, namespace, name, user_id, desired_template_id,
              desired_release_id, applied_release_id, desired_power_id, applied_power_id,
              pause_when_idle) on deployment to activator;
grant select (id, product_id) on product_template_version to activator;
grant select (id, name) on product to activator;
grant select (id, state, reason, ended_at) on deployment_power to activator;
grant select (id, deployment_id, status) on deployment_reconcile_job to activator;
grant select (deployment_id, initiated_by_user_id, ended_at) on deployment_release to activator;
grant select (deployment_id, status, finished_at) on build to activator;
```

`pause_when_idle` defaults to false so that its migration pauses nothing; new deployments take the catalog's `pause.idle` default at creation. Releases that predate `initiated_by_user_id` stay null, i.e. they count as platform releases.

### Later queries

This is the contract between the activator, the power-request tick and the reconciler. Status literals are those in `api/app/services/reconcile_constants.py` and `build_constants.py`.

#### What "in flight" means

A deployment is left alone, by the idle loop and by the tick's re-check, unless all of these hold. Each condition rules out a different kind of change in progress:

| Condition | Rules out |
| --- | --- |
| `d.status = 'ready'` | Awaiting payment, provisioning, deleting, or failed (`error`) |
| `d.applied_release_id = d.desired_release_id` | A release that is queued, being applied, or failed and rolled back |
| `d.desired_power_id is not distinct from d.applied_power_id` | A stop, pause or start that has been asked for but not yet applied |
| Latest reconcile job has `status = 'done'` | A job that is `queued` or `running`, or a last job that `failed` |
| No build with `status in ('queued', 'running')` | An owner build in progress, which will usually be followed by a deploy |

The first two overlap: only a successful reconcile sets `ready`, and it sets `applied_release_id` in the same transaction. The release condition is still written out, because it says directly what the queries mean and costs nothing. `is not distinct from` is needed because both power pointers are null for a deployment that was never stopped or paused.

#### Activator: host lookup

Run for every request the activator receives. The `lower(hostname)` predicate and `status <> 'deleted'` match the `uq_hostname_active` index.

```sql
select d.id, d.status, p.name as product_name,
       coalesce(pw.state, 'running') as desired_state,
       pw.reason
from deployment d
join product_template_version t on t.id = d.desired_template_id
join product p on p.id = t.product_id
left join deployment_power pw on pw.id = d.desired_power_id
where lower(d.hostname) = lower($1)  -- the request's Host, without port
  and d.status <> 'deleted';
```

What the activator does with the row:

| Row | Page | Files a start request |
| --- | --- | --- |
| `desired_state = 'running'` (a start is in flight, or Traefik has not yet switched back to the app) | Starting up | No |
| `desired_state = 'paused'`, `status = 'ready'` | Starting up | Yes |
| `desired_state = 'stopped'`, `reason = 'payment'` | Unavailable | No |
| `desired_state = 'stopped'`, otherwise | Stopped | No |
| `status` other than `ready` while not running, or no row | Unavailable | No |

```sql
insert into deployment_start_request (deployment_id) values ($1) on conflict do nothing;
```

#### Activator: idle candidates

Run once per idle-loop pass. `$1` is the current UTC time minus the idle window. The result is every deployment that:
- is not in flight;
- is running;
- has `pause_when_idle` on;
- has no owner activity in the database more recent than the window.

The Prometheus evidence is then checked for exactly these rows.

```sql
select d.id,
       d.namespace || '-' || d.name || '-' as router_prefix,
       j.id as expected_job_id
from deployment d
join lateral (
    select id, status
    from deployment_reconcile_job
    where deployment_id = d.id
    order by id desc
    limit 1
) j on true
left join deployment_power pw on pw.id = d.desired_power_id
where d.status = 'ready'
  and d.hostname is not null
  and d.pause_when_idle
  and d.applied_release_id = d.desired_release_id
  and d.desired_power_id is not distinct from d.applied_power_id
  and coalesce(pw.state, 'running') = 'running'
  and j.status = 'done'
  and not exists (
      select 1 from build b
      where b.deployment_id = d.id and b.status in ('queued', 'running')
  )
  -- the countdown restarts on an owner release, a finished build, or a start
  and coalesce(greatest(
      (select max(r.ended_at) from deployment_release r
        where r.deployment_id = d.id and r.initiated_by_user_id = d.user_id),
      (select max(b.finished_at) from build b where b.deployment_id = d.id),
      (select ap.ended_at from deployment_power ap
        where ap.id = d.applied_power_id and ap.state = 'running')
  ), '-infinity'::timestamp) < $1;
```

`greatest` ignores nulls, so a deployment with no owner release, build or start on record is judged on traffic alone.

#### Activator: the idle decision

For each candidate, the loop matches every series of the router query (Idle detection, above) whose `router` label starts with `router_prefix` and ends in `@kubernetes` or `@kubernetescrd`. This is the same match as `router_pattern` in `api/app/services/http_logs.py`. A candidate is idle when all of these hold:

- the coverage query returned a result in this pass;
- every matching series has an `increase` of zero;
- no matching series is younger than the window.

A candidate with no matching series at all is idle too: with coverage established, that means no request in the window. For each idle candidate:

```sql
insert into deployment_pause_request (deployment_id, expected_job_id)
values ($1, $2)
on conflict do nothing;
```

#### Tick: consuming requests

The tick reads the open request ids once per pass and handles each id in its own transaction. A request it keeps (a start behind an open job) therefore waits for the next pass instead of spinning, and one failure does not block the rest.

The locking relies on one invariant: **every path that enqueues a reconcile job writes the deployment row in the same transaction.** Create inserts it; update, delete and the first-payment webhook update it; the power service functions lock it. Holding the row lock therefore serializes the tick against every job creator.

The re-check runs as a separate statement after the lock is granted. Under `READ COMMITTED`, every statement takes a fresh snapshot, so the re-check sees any job committed while the tick waited for the lock. Folding the check into the locking `SELECT … FOR UPDATE` would not: Postgres re-evaluates the locked row but not the subqueries against the job table.

A pause request, in one transaction:

```sql
-- 1. claim it; another worker already holding it means skip
select expected_job_id from deployment_pause_request
where deployment_id = :deployment_id
for update skip locked;

-- 2. serialize against every job creator
select id from deployment where id = :deployment_id for update;

-- 3. re-check, in a new statement
select 1
from deployment d
join lateral (
    select id, status from deployment_reconcile_job
    where deployment_id = d.id order by id desc limit 1
) j on true
left join deployment_power pw on pw.id = d.desired_power_id
where d.id = :deployment_id
  and d.status = 'ready'
  and d.pause_when_idle
  and d.applied_release_id = d.desired_release_id
  and d.desired_power_id is not distinct from d.applied_power_id
  and coalesce(pw.state, 'running') = 'running'
  and j.id = :expected_job_id
  and j.status = 'done';

-- 4. if step 3 returned a row: the pause service function inserts a
--    'paused' power row (reason 'idle', actor null), points
--    desired_power_id at it and enqueues the reconcile job

-- 5. in every case
delete from deployment_pause_request where deployment_id = :deployment_id;
```

A start request, in one transaction:

```sql
select 1 from deployment_start_request
where deployment_id = :deployment_id
for update skip locked;

select id from deployment where id = :deployment_id for update;

select 1
from deployment d
join deployment_power pw on pw.id = d.desired_power_id
where d.id = :deployment_id
  and d.status = 'ready'
  and pw.state = 'paused';

-- row: the start service function inserts a 'running' power row (reason
--      'traffic'), points desired_power_id at it and enqueues the reconcile
--      job; then delete. DeploymentInProgressException (a job is still open,
--      e.g. the pause being applied): roll back, which keeps the request for
--      the next pass.
-- no row: not eligible; delete.
delete from deployment_start_request where deployment_id = :deployment_id;
```

The start check deliberately does not require desired and applied power to agree. A start that arrives while its pause is still being applied is eligible. It fails to enqueue only because that job is open, and it is retried once the job finishes.

Because the tick holds the deployment row lock, an owner update that lands at the same moment waits for the tick to commit. Its own enqueue then meets the open pause job and gets the usual 409 "operation in progress". The window is a few milliseconds, and the owner retries.

### Cold-start experience

The activator answers immediately and by what kind of client is asking, with a 503 that every client understands as temporary.

| Request | Paused | Stopped or unavailable |
| --- | --- | --- |
| Browser navigation (`GET`, `Accept: text/html`) | Branded "\<app> is starting up" page, `503`, `Retry-After`, `Cache-Control: no-store`; the page polls its own URL and reloads on the first status that is not 503. After the product's `cold_start_seconds` it adds a "taking longer than usual" note. | Branded "\<app> is stopped" or "\<app> is unavailable" page, `503`, no polling |
| Anything else (API calls, `POST`, mobile and desktop sync clients) | `text/plain` with the same sentence, `503`, `Retry-After`, which sync clients already handle | `text/plain` with the same sentence, `503` |
| WebSocket upgrades | `503` | `503` |

A paused app's first request files the start request. The polling page and retrying clients keep hitting the activator until Helm restores the Ingress. From then until the pods are ready, Traefik answers 503 itself, so the page keeps waiting and clients keep retrying. Only a visitor who reloads by hand during that interval sees Traefik's plain "Service Unavailable" instead of the branded page.

The activator's pages share the layout and design of the `custom` product's placeholder page (`products/custom/placeholder/index.html`), so a tenant hostname looks the same whether it is waiting for a first deploy or starting up. Only the copy differs.

Start times vary a lot by product. Mattermost or Vaultwarden should be back in seconds, while Discourse or OpenProject boot a Rails app and may take a minute or more. These are estimates, not measurements; each catalog product records a measured `cold_start_seconds`. The deployment row in the UI shows Paused or Stopped, and Pausing, Stopping or Starting while desired and applied power differ; the CLI reports the same wherever it shows a deployment.

### Stateful apps and edge cases

Stateful apps stop and pause safely because everything durable is either outside the namespace or on a PVC that survives scale-to-zero.

- **In-chart databases.** Lemmy, Mattermost, Nextcloud, Discourse, Docmost and OpenProject run their own Postgres or Redis StatefulSets. Scaling a StatefulSet to 0 keeps its PVCs, and the database gets its normal shutdown signal. On start everything boots at once and apps retry until their database answers, as they already do on a cold rollout. Scaling to 0 and back never runs two database pods on one volume. Platform tenant databases and Garage buckets are shared services and are not touched at all.
- **Several workloads per release.** Handled for free: the post-renderer rewrites every workload in the release, not "the" Deployment, and Helm's `--wait` on the start render waits for all of them.
- **Network policy.** The activator's namespace admits Traefik, and its egress reaches only Postgres and Prometheus. Tenant policies are unchanged, since the activator never connects to tenant pods.
- **SSH.** The SSH sidecar runs in the app's pod, so SSH to a stopped or paused deployment authenticates and then reaches nothing. SSH never starts a deployment. ssh-auth, which already reads the database, could say that the app is paused or stopped instead.
- **Background work.** CronJobs, email digests, federation and scheduled jobs stop while an app is not running. That is the main reason some products should never auto-pause (next section).
- **Images.** The image of an app that has been down for a long time may be garbage-collected from the node, making the next start slower. The tenant registry's retention rule is computed from the release ledger, so the image of a stopped or paused release is still kept in the registry.
- **Start storms.** Crawlers or link previews can start paused apps that have no auth. Each spurious start costs one idle window of resources. The reconcile worker pool already bounds how many start at once.
- **Usage.** OpenCost will show near-zero CPU and memory while an app is not running, so the usage ledger reflects savings automatically. Storage keeps accruing, as intended.
- **Upgrades that cannot skip versions.** Nextcloud upgrades only one major version at a time, and its image refuses to start otherwise. A Nextcloud that receives two major rollouts without booting fails at its next start. This is the general problem of a deployment falling more than one major behind, which stepwise rollouts solve for running and stopped deployments alike; stopping and pausing only make it more likely.

### Which products will actually go idle

Auto-pause will mostly pay off for custom apps, demos and lightly used catalog apps, because anything with a connected client never sees an hour without requests.

| Product | Likely to go idle? | Why | Idle pause for new deployments |
| --- | --- | --- | --- |
| App Studio | Often | Heavy, and does nothing useful while the owner is away. Its SSE-driven UI can look idle while a tab is open (see Idle detection). | On |
| `custom` | Often | Hobby apps and demos get bursts of traffic | On |
| BookStack, Docmost, PhotoPrism, Lemmy (small) | Often | Browser-only use | On |
| Immich, Nextcloud, Vaultwarden | Rarely | Mobile and desktop clients poll or sync in the background | On; it just won't trigger while clients are connected |
| Matrix | Rarely | Federation traffic arrives from other servers | On |
| Mattermost, Discourse, OpenProject | Sometimes | Email digests, notifications and scheduled jobs stop while paused | Off |

The idle window is one caelus setting (default 1 hour), not a per-product value. The catalog YAML only sets each product's default for new deployments (`pause.idle: on | off`) and its measured `cold_start_seconds`. The setting is copied onto the deployment when it is created, so the owner can always toggle it in the Edit dialog and the CLI, and a later change to the catalog default never flips existing deployments. Any request counts as activity in the first version; filtering out bots and health checks can come later if it matters.

App Studio's preview host (`preview-<app>-<handle>`) stays outside this subsystem. App Studio's own idle handling already stops the preview and starts it again when a browser reconnects to the studio, so the post-renderer does not rewrite the preview's Ingress and the activator never sees it. While the studio is paused, the preview answers 503 until the owner opens the studio, which starts it.

### Stop, pause, start and payment

Manual stop and start use the same state machine as everything else with a different trigger, so they are the natural first deliverable.

| Trigger | `state` | `reason` | What a visitor sees |
| --- | --- | --- | --- |
| Owner clicks **Pause** | `paused` | `manual` | "Starting up" page, app starts |
| Owner clicks **Stop** | `stopped` | `manual` | "This app is stopped" page; the owner sees a Start button after signing in |
| No traffic for the idle window | `paused` | `idle` | "Starting up" page, app starts |
| Subscription in arrears | `stopped` | `payment` | "Unavailable" page; only payment starts it |

A stopped app is never started as a side effect: not by traffic, not by SSH, not by a CLI deploy. Only Start on the dashboard, `freepod start` and the API's start route run it again.

| Action | API | `caelus` | `freepod` | Dashboard |
| --- | --- | --- | --- | --- |
| Stop | `POST .../deployments/{id}/stop` | `stop-deployment` | `freepod stop` | Stop |
| Pause (phase 2) | `POST .../deployments/{id}/pause` | `pause-deployment` | `freepod pause` | Pause |
| Start | `POST .../deployments/{id}/start` | `start-deployment` | `freepod start` | Start |

The public start route and the power-request tick are two thin entry points to one service function. The public one is owner-authorized and starts any deployment the owner may start: paused, or stopped with reason `manual`; a payment stop is refused with `not_startable`. The tick has no caller identity and only starts paused deployments. Payment enforcement is a free by-product: `deployment-payment-states` already tracks `arrears` but nothing acts on it.

### Phasing

Each phase ships something usable on its own, and phase 1 already builds the parts phase 2 needs.

1. **Stop and start** (OpenSpec change `stop-and-start-deployments`):
   - `deployment_power` and the power pointers;
   - the reconciler's power branch;
   - the `--suspended` post-render step;
   - `allowEmptyServices` on Traefik;
   - stop and start in the API, `caelus`, the `freepod` CLI and the deployment row.

   The activator ships in its simplest form: a static "stopped" page.
2. **Pause and start on traffic:**
   - `deployment_start_request` and the power-request tick;
   - the activator's database role, eligibility check, start requests and "starting up" page;
   - Pause in the API, `caelus`, `freepod` and the dashboard.
3. **Idle pause:**
   - the activator's idle loop with its coverage guards;
   - `deployment_pause_request` with its compare-and-set;
   - `initiated_by_user_id` and the `actor` argument;
   - the catalog `pause.idle` policy and the per-deployment override;
   - measured `cold_start_seconds` per product.
4. **Extras:**
   - stopping for payment arrears;
   - a faster start path if Helm latency matters;
   - bot filtering if spurious starts become a cost;
   - stepwise rollouts for products that cannot skip major versions;
   - a capacity policy for nodes that cannot hold every deployment running.

Phases 1 and 2 are each about one openspec change; phase 3 is small once 2 exists. Phase 1 proves the post-renderer approach against Helm's three-way merge, and the 503 hand-over, on the `custom` product in dev before anything else is built.

### Open questions

- [x] Should owners be able to change the idle window, or only opt in and out? (Decided: the window itself is one caelus setting.)
- [x] Should a stopped or paused app cost less? (Decided: billing is moving entirely to usage-based, so an app that is not running is billed for little more than its storage, with no special pricing rule needed.)
- [x] Should anonymous traffic be allowed to start a paused app without `auth.enabled`, or only signed-in visitors? (Decided: any visitor can start a public app; only apps with `auth.enabled` require sign-in first, because app-auth runs before the activator.)
- [x] Should the activator hold requests and proxy them once the app is up? (Decided: no. It answers 503 immediately; holding invites a pile-up of connections and would need to know every chart's backends.)
- [x] Should the idle sweep understand app-specific activity, such as App Studio's agent sessions or open WebSockets? (Decided: no. The sweep knows only router request counts.)
- [x] What are the actions called? (Decided: stop, pause and start, with states stopped, paused and running, on every surface. See Vocabulary.)
- [ ] Is a minute-long cold start acceptable for Discourse and OpenProject, or should they simply be excluded from auto-pause? (Deferred: decide once cold starts are measured.)
- [ ] What happens when a node cannot hold every deployment running at once? A start that cannot be scheduled sits pending until Helm's timeout and rolls back to paused or stopped. (Deferred: capacity and overcommit policy comes later.)
