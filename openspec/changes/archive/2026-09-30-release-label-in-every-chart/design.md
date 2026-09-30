## Context

`custom` is the only chart that renders `caelus.releaseId`. It does so through `custom.podLabels`
in `products/custom/chart/templates/_helpers.tpl`, which is included only in the pod template.
The platform knows which charts render the label from a hand-kept list,
`CHARTS_RENDERING_RELEASE_LABEL` in `api/app/services/deployment_logs.py`. Two places read it: the
pinned log read, which refuses with `LogAttributionUnavailable`, and the reconciler's failure tail,
which falls back to a time-bounded deployment selector.

Every curated chart already accepts the value, because each `values.schema.json` leaves `caelus`
open (`mattermost` has no schema at all). `api/tests/test_curated_charts_ignore_release_id.py`
confirms that they render with it and ignore it.

The workloads and how they are classified:

| chart       | application workloads                                      | datastores                     |
|-------------|------------------------------------------------------------|--------------------------------|
| bookstack   | `bookstack.yaml`                                           | `mysql.yaml`                   |
| helloworld  | `deployment.yaml`                                          | —                              |
| immich      | `server.yaml`, `machine-learning.yaml`                     | `postgres.yaml`, `valkey.yaml` |
| lemmy       | `lemmy.yaml`, `lemmy-ui.yaml`, `pictrs.yaml`, `proxy.yaml` | `postgres.yaml`                |
| matrix      | `statefulset.yaml` (Synapse), `element-web.yaml`           | —                              |
| mattermost  | `deployment.yaml`                                          | `postgresql.yaml`              |
| naas        | `deployment.yaml`                                          | —                              |
| nextcloud   | `nextcloud.yaml`                                           | `postgres.yaml`                |
| photoprism  | `photoprism.yaml`                                          | `mariadb.yaml`                 |
| vaultwarden | `vaultwarden.yaml`, `bootstrap-job.yaml` (hook Job)        | —                              |

The SSH sidecar is a container inside the application pod, not a separate workload, so it gets
the label with that pod. The log reader already excludes its container.

## Goals / Non-Goals

**Goals:**
- Make the label a property of the product tree that CI checks, not something each chart opts
  into.
- Remove every chart-dependent branch from the log read and the failure tail.

**Non-Goals:**
- Labeling datastores, or giving datastore logs release attribution. Their output stays readable
  in the unpinned stream.
- Recording on each release whether its pods were labeled. See Decision 3.
- `caelus.releaseNumber`. Only the SSH sidecar banner consumes it, and that is a separate concern.

## Decisions

### 1. One `<chart>.podLabels` helper per chart, copied from `custom`

Each chart gets its own `<chart>.podLabels` helper, identical to `custom.podLabels`. It emits
nothing when `releaseId` is empty. The helper is included in each application workload's
`spec.template.metadata.labels` and nowhere else. Each chart also gets `caelus.releaseId: ""` in
`values.yaml` so it renders standalone.

The other option was a helper in `_lib`, shared the way `ssh-sidecar` is. That would add a
subchart dependency to three charts that have none (helloworld, naas, matrix) in order to share
three lines of template. The contract test (Decision 2) already keeps the copies consistent, so
the dependency is not worth it. The rationale comment stays in `custom`'s helper only; the copies
point to it.

### 2. A contract test over every chart, with datastores declared in the test

`test_curated_charts_ignore_release_id.py` is replaced by a test that discovers every
`products/*/chart` and renders it twice with `helm template`: once with a release ID and once
without. For each pod-bearing object (Deployment, StatefulSet, Job), identified by the
`# Source:` path in helm's output, it asserts:
- with an ID, an application workload's pod template carries it, and neither its
  `spec.selector` nor any Service selector does;
- with an ID, a datastore's pod template does **not** carry it;
- without an ID, no object carries the label.

The test holds datastores in an explicit map from chart to source file. It discovers charts, so a
new chart is covered automatically, and it discovers workloads, so every workload is labeled
unless it is declared a datastore. A datastore that is not declared fails the test, so leaving
one out is caught.

The alternative was a marker label on datastore pods, such as `caelus.dev/role: datastore`. That
would change every datastore's pod template once, so every database restarts on rollout, only to
record something the test can hold itself.

The existing test's fixture that resolves chart dependencies, and its per-chart minimum values,
carry over.

### 3. Drop the platform-side list outright; accept a bounded gap for old releases

Pinning is always offered, and the failure tail is always queried by release. The list, its two
helpers, and the `LogAttributionUnavailable` exception are removed.

The cost falls on releases applied before the new charts. Their pods carry no label, so a pinned
read of one returns an empty stream. That is the misleading answer the list existed to prevent.
The gap has two limits:
- **Current releases.** The migration plan moves every deployment onto the new canonical
  template, so every live pod is labeled once rollout finishes.
- **Past releases.** Loki keeps logs for 336h (`tf/deps/loki/main.tf`). Fourteen days after
  rollout, no unlabeled release output is left to pin.

The alternative was to keep an honest answer by recording a `labels_pods` flag on each release.
The reconciler would read it from the rendered manifest at apply time, and releases from before
the change would be backfilled from their chart. That means a migration and a new write in the
apply path, permanently, to cover a gap that closes on its own in two weeks. It is not worth it.

### 4. Version bumps are patch-level, following each chart's history

Each chart's version gets the next patch number, and its catalog `chart_version` is repointed to
match. No existing tag is republished, because CI's `publish-charts.sh --skip-if-published` would
skip it silently.

## Risks / Trade-offs

- [Every new release restarts application pods, even when values are unchanged] → This is already
  true of `custom` and of any change to a var (the Secret is named per release). At one replica
  this causes a brief interruption per apply, which is the accepted cost recorded in `custom`'s
  helper. Datastores are excluded, so no database restarts.
- [Pinned reads of releases from before the change return empty for up to 14 days] → See
  Decision 3. This is recorded in the deployment-log-api delta as the one allowed empty answer.
- [The nightly upgrader rewrites a chart and drops the helper include] → The contract test fails
  in CI on the upgrader's PR, naming the chart and the workload.
- [A new application workload is added to a chart without the include] → The test covers it
  unless the workload is declared a datastore, and declaring one is a visible, reviewable edit.
- [Upstream chart dependencies, if any are added later, render pods the chart cannot label] →
  The test then fails on the subchart's workloads. That forces a decision at that point, either
  labeling through the subchart's pod-labels value or declaring the workload exempt.

## Migration Plan

1. Merge. CI publishes the ten new chart versions to ghcr.io, and each environment's
   `caelus catalog apply` (run at API startup) creates the new canonical templates.
2. Deploy the API change in the same rollout. Order does not matter: the old API refuses to pin
   curated products, and the new one pins them against pods that are labeled or soon will be.
3. For each existing deployment of a curated product, per environment, run
   `caelus update-deployment` onto its product's canonical template. This creates a labeled
   release, and the application pods restart once. Do dev first and confirm a pinned
   `freepod log --release N` returns output for one deployment of each product.
4. Rollback: repoint the catalog to the previous `chart_version`s. Those tags are still in the
   registry. Reverting the API change restores the list. Deployments already moved stay on the
   labeled charts, which is harmless.
