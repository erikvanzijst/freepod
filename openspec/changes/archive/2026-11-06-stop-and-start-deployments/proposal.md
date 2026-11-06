# Proposal

## Why

A deployment today is either running or deleted. An owner who wants to take an app offline without losing its data has no way to do it, and the platform has no way to free the CPU and memory of an app nobody uses. This change adds **stop** and **start**: a stopped deployment keeps all of its data, runs nothing, and comes back only when someone explicitly starts it.

It is the first phase of a subsystem with two independent mechanisms:
- **Stop and start**, owned by Freepod: this change.
- **Pause when idle and wake on traffic**, a later change delegated to Sablier, driven by a Traefik middleware.

The design's appendix restates what that phase needs from this one, so that nothing here has to be reworked.

## What Changes

- **A power state.** A deployment gains a power state, `running` or `stopped`. It is recorded as append-only rows in a new `deployment_power` table, with desired and applied pointers on the deployment, and sits beside `status`: a stopped deployment is still `ready`.
- **Stop and start.** Owners and administrators stop and start a deployment through `POST .../stop` and `POST .../start`, with `caelus stop-deployment` and `caelus start-deployment` in parity.
  - A power change is accepted only for a `ready` deployment.
  - Start lifts only a `manual` stop. The `payment` reason is reserved for a later phase.
- **Power is applied outside the release ledger.** A reconcile that only changes power creates, claims and rewrites no release. Releases applied to a stopped deployment are rendered stopped and stay stopped.
- **A stopped render in the post-renderer:**
  - Deployments and StatefulSets go to 0 replicas, owned by Helm, and Jobs and CronJobs are suspended.
  - HPAs and bare Pods are dropped.
  - The deployment's own hostname is routed to the parking page through a per-release `ExternalName` Service.

  After applying a stopped render, the reconciler scales any workload that is still above 0 replicas down to 0.
- **The parking page is served by the existing API** (`caelus-api`), not by a new daemon. A host guard, the outermost layer of the API, answers every request whose `Host` is not the API's own domain with `503`: an HTML "stopped" page for browser navigations, plain text otherwise. That request never reaches an API route, so forged identity headers sent to a stopped app's hostname cannot reach the API. Loopback peers are exempt, for operators' `port-forward`.
- **Helm hooks are banned in catalog charts.** A test enforces it. Vaultwarden, the only chart with a hook, moves its owner invitation from a `post-install,post-upgrade` Job into a `postStart` hook on its container (chart 3.5.0), so that nothing ever runs against a deployment at 0 replicas.
- **The `freepod` CLI** gains `freepod stop` and `freepod start` (minor version bump), and `freepod deploy` says when the deployment it updated is stopped.
- **The dashboard** shows Stopped, Stopping and Starting, and offers Stop and Start.
- **Traefik needs no change.** Routers without ready endpoints already answer `503`, not `404`: chart 41.5.0 enables `allowEmptyServices` by default, and the live Traefik has the flag. This change relies on that and verifies it.

The same words name every action and state on every surface: stop and start; stopped and running.

## Capabilities

### New Capabilities

- `deployment-power-data-model`: the `deployment_power` ledger, the desired and applied power pointers, and the power fields on deployment reads.
- `deployment-power-api`: stop and start through REST and `caelus`: preconditions, idempotence, authorization and errors.
- `deployment-power-reconciliation`: how the reconciler applies power, the stopped render, the post-stop sweep, the ban on Helm hooks, and the edge behavior (503 for routers without endpoints) that a stopped or starting app relies on.
- `parking-page`: the API's host guard and the responses served for hostnames of stopped apps.
- `vaultwarden-owner-invite`: how a Vaultwarden deployment invites its owner without a Helm hook.
- `cli-power`: `freepod stop` and `freepod start`, and how the CLI reports a stopped deployment.
- `deployment-power-ui`: the dashboard's Stop and Start actions and its power-state labels.

### Modified Capabilities

- `deployment-release-ledger`: a reconcile that only changes power is not a rollout, so it creates, claims and rewrites no release.

## Impact

- **Database:** an Alembic migration adds the `deployment_power` table and the `desired_power_id` and `applied_power_id` columns on `deployment`. Existing deployments need no backfill: null means running.
- **API:**
  - a new power service in `api/app/services/power.py`, and the power branch in `services/reconcile.py`;
  - the stopped render in `post_render.py`, and the render, release and parking arguments in `provisioner.py`;
  - the parking guard and page in `api/app/parking.py`, installed outermost in `main.py`;
  - the routes in `api/app/api/users.py`, `caelus stop-deployment` and `caelus start-deployment` in `cli.py`;
  - the read models' power fields.
- **Charts:** `products/vaultwarden` 3.4.7 → 3.5.0, with the bootstrap Job replaced by a `postStart` hook and `bootstrap.image` removed, and its catalog template moved to 3.5.0. A chart test bans `helm.sh/hook` documents in every catalog chart.
- **Terraform:** `tf/app/caelus` sets `CAELUS_PARKING_HOST` and `CAELUS_PARKING_PORT` in the API and worker configmap. `tf/deps` is unchanged.
- **CLI:** new commands and a minor version bump in `cli/src/freepod/`, and a regenerated `cli-reference` in `ui/docs`.
- **UI:** `ui/src/components/deployment/` (view model, row), `ui/src/pages/Dashboard.tsx` (polling) and `ui/src/api/types.ts`.
- **Docs:** pages in `ui/docs` for owners and developers, the Vaultwarden README, and an `AGENTS.md` orientation entry.
- **Compatibility:** purely additive. Older `freepod` clients keep working, so `MIN_CLIENT_VERSION` is not raised.
- **Ordering:** the Vaultwarden 3.5.0 rollout to every Vaultwarden deployment must finish before the stop routes ship (design, Migration Plan).
