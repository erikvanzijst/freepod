# Proposal

## Why

A deployment today is either running or deleted. An owner who wants to take an app offline without losing its data has no way to do it, and the platform has no way to free the CPU and memory of an app nobody is using. Stopping is the foundation for pausing (an app that starts again on its next visitor), idle auto-pause and payment enforcement, which later changes add. Stop and start ship first because they build the machinery all of those share, and because they prove the core mechanism against Helm's three-way merge before anything is built on top: rendering a release with nothing running, through the Helm post-renderer.

## What Changes

- A deployment gains a **power state**: `running`, `paused` or `stopped`. It is recorded as append-only rows in a new `deployment_power` table, with desired and applied pointers on the deployment, and sits alongside `status`: a stopped deployment is still `ready`. This change produces `running` and `stopped`; `paused` is in the schema for later phases.
- Owners (and administrators) can **stop** and **start** a deployment through `POST .../stop` and `POST .../start`, with `caelus stop-deployment` and `caelus start-deployment` in parity. A power change is accepted only for a `ready` deployment.
- The reconciler applies power changes **outside the release ledger**. A reconcile that only changes power creates, claims and rewrites no release. Releases applied to a stopped deployment are rendered stopped.
- The platform post-renderer gains a **suspended render**, the internal term for a render in which nothing runs, used for both stopped and paused deployments:
  - Deployments and StatefulSets go to 0 replicas, and Jobs and CronJobs are suspended.
  - HPAs, bare Pods and Helm hook documents are dropped.
  - The deployment's own hostname is routed to the activator through a per-release `ExternalName` Service.
- A new Go daemon, the **activator** (`daemons/activator/`), deployed per environment, answers every request for a stopped app with a 503: a branded "stopped" page for browsers, plain text for everything else. In this phase it is stateless. Pausing, starting on traffic, the database role and the idle loop come in later phases.
- Traefik's Kubernetes Ingress provider sets **`allowEmptyServices: true`**, so a router whose Service has no ready endpoints answers 503 instead of 404. This changes behavior cluster-wide, for dev and prod: any app without ready pods answers 503.
- The `freepod` CLI gains **`freepod stop`** and **`freepod start`** (minor version bump), and `freepod deploy` says when the deployment it updated is stopped.
- The dashboard's deployment row shows **Stopped**, **Stopping** and **Starting**, and offers **Stop** and **Start** actions.

The same three words name every action and state on every surface: stop, pause, start; stopped, paused, running.

## Capabilities

### New Capabilities

- `deployment-power-data-model`: the `deployment_power` ledger, the desired and applied power pointers, and how power is exposed on deployment reads.
- `deployment-power-api`: stop and start through REST and `caelus`, including preconditions, idempotence, authorization and errors.
- `deployment-power-reconciliation`: how the reconciler applies power, the post-renderer's suspended render, and the edge behavior (`allowEmptyServices`) a stopped or starting app relies on.
- `app-activator`: the activator daemon, its responses for hostnames of apps that are not running, and how it is deployed.
- `cli-power`: `freepod stop` and `freepod start`, and how the CLI reports a stopped deployment.
- `deployment-power-ui`: the dashboard's Stop and Start actions and its power-state labels.

### Modified Capabilities

- `deployment-release-ledger`: a reconcile that only changes power is not a rollout, so it creates, claims and rewrites no release.

## Impact

- **Database:** an Alembic migration adds the `deployment_power` table, the `desired_power_id` and `applied_power_id` columns on `deployment`. Existing deployments need no backfill (null means running).
- **API:**
  - `api/app/services/` gets a new power service, and `reconcile.py` gets the power branch.
  - `post_render.py` gets the suspended render, `provisioner.py` the suspended and activator arguments, and the deployment read models their power fields.
  - New routes go in `api/app/api/users.py`, with `caelus stop-deployment` and `caelus start-deployment` in `cli.py`.
- **Daemons:** a new `daemons/activator/` module, shipped in the existing daemons image. Bumping `daemons/VERSION` releases it.
- **Terraform:**
  - `tf/app` gets the activator Deployment, Service and NetworkPolicy per environment, plus the activator address passed to the API and worker.
  - `tf/deps/system/helm/traefik` gets `allowEmptyServices`, a cluster-wide change that restarts Traefik.
- **CLI:** `cli/src/freepod/` gets new commands and a minor version bump, and `ui/docs` gets a regenerated `cli-reference`.
- **UI:** `ui/src/components/deployment/` (view model, row, toolbar), `ui/src/pages/Dashboard.tsx` (polling) and `ui/src/api/types.ts`.
- **Docs:** `ui/docs` developer and app pages on stopping and starting, and an `AGENTS.md` orientation entry.
- **Compatibility:** purely additive. Older `freepod` clients keep working, so `MIN_CLIENT_VERSION` is not raised.
