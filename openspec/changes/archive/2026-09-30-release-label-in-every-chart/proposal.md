## Why

Release attribution of logs works for `custom` only. The reconciler hands `caelus.releaseId` to
every chart, but the nine curated charts ignore it. So a curated deployment's log cannot be
pinned to a release, a failed rollout's error tail falls back to a time-bounded deployment query,
and the CLI cannot announce rollovers. The adoption was tracked in an ad-hoc `todo/033` note that
never reached a spec, and it was forgotten. Making the label universal also lets the platform stop
tracking which charts render it.

## What Changes

- Every chart under `products/` renders `caelus.dev/release-id` on the pod template of each
  **application** workload: every pod that runs the product's own code, including helper
  processes and hook Jobs. Datastore workloads (Postgres, MySQL, MariaDB, Valkey) do not get the
  label, so an apply never restarts a database.
- Each chart gets a version bump, and its catalog entry is repointed to the new `chart_version`.
- A contract test renders **every** chart under `products/` and fails when an application workload
  lacks the label or a datastore carries it. That makes the label a condition for adding a chart,
  rather than something a chart may opt into.
- **BREAKING (API)**: the platform drops `CHARTS_RENDERING_RELEASE_LABEL` and always pins. A
  pinned log read no longer returns "release attribution is unavailable". The error tail of a
  failed release is always queried by release.
- Rollout moves every existing deployment onto the new canonical template, so no **current**
  release keeps writing unlabeled output. Releases from before the change can still be pinned,
  but they return empty until Loki's 14-day retention removes their unlabeled lines.
- `todo/033-releaseid-adoption-in-curated-charts.md` is superseded by this change.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `release-log-labeling`: rendering the identifier stops being each chart's decision. Every
  product chart SHALL stamp it on its application pods and SHALL NOT stamp it on datastore pods.
- `deployment-log-api`: pinning is offered for every deployment. The "attribution unavailable"
  answer is removed, and the requirement records the transitional behavior for releases from
  before the change.
- `cli-log`: the "pinning where the product does not support it" scenario is removed, because the
  server no longer produces that answer.

## Impact

- **Charts**: `bookstack`, `helloworld`, `immich`, `lemmy`, `matrix`, `mattermost`, `naas`,
  `nextcloud`, `photoprism` and `vaultwarden` each get a pod-label helper, a pod-template include,
  a `caelus.releaseId` default in `values.yaml`, and a chart version bump. Their catalog files are
  repointed. Every application pod restarts once on its next apply, and after that on every new
  release, as `custom`'s pods already do.
- **API**: `api/app/services/deployment_logs.py` loses `CHARTS_RENDERING_RELEASE_LABEL`,
  `_chart_name`, `_renders_release_labels` and `LogAttributionUnavailable`.
  `api/app/services/reconcile.py` always pins the failure tail. The 400 case is removed from the
  endpoint docs in `api/app/api/users.py`.
- **Tests**: `api/tests/test_curated_charts_ignore_release_id.py` is replaced by an every-chart
  contract test. Pinning and failure-tail tests that assert the fallback are removed or inverted.
- **Operations**: after the charts are published and the catalog is applied, each existing
  deployment gets one `update-deployment` onto its canonical template.
- **Upgrader**: charts the nightly upgrader adds or rewrites must pass the contract test, so the
  label survives automated upgrades.
