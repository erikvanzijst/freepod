## Why

Two questions come up often and neither has a quick answer today:

- **What is each deployment using?** CPU, memory and network are in
  Prometheus per namespace, database sizes per `datname`, and bucket sizes per
  `dep-<deployment id>` bucket, but nothing joins the three. A namespace says
  nothing about which database or bucket is its own, so the only way to line
  them up is to look the deployment up in the platform database by hand.
- **What happened to this one deployment?** Its pod output and its Traefik
  access lines are both in Loki, under different selectors, and lining them
  up means two Explore tabs and matching timestamps by eye.

`tenant-usage.json` answers a third question (usage against requests, for
capacity planning) and stays as it is.

## What Changes

- The reconciler labels each deployment namespace with
  `caelus.dev/deployment-id`, and kube-state-metrics publishes it on
  `kube_namespace_labels`. That one label joins a namespace to its database
  (`datname` is the ID without hyphens) and its bucket (`dep-<id>`).
  `caelus sync-network-policies` backfills existing namespaces.
- **Freepod: deployments**: one row per deployment in an environment, with
  hostname, product, owner, CPU, memory, pod network, HTTP requests, database,
  bucket and PVC sizes and restarts, plus top-10 graphs over time. A hostname
  links to the deployment's own dashboard.
- **Freepod: deployment**: one deployment, picked by hostname, deployment ID or
  namespace. It shows health, resources by container, Traefik's view of its
  HTTP traffic, its database statistics, its storage, and its pod logs above
  its Traefik access lines on one shared time axis. Pod creations are marked
  on every graph.

Both dashboards read only what is collected today. No scrape, exporter,
collector or Promtail stage changes, and no new stream or series label beyond
one namespace label.

## Capabilities

### Modified Capabilities

- `monitoring-dashboards-access`: the deployment identity label, and the two
  deployment dashboards.

## Impact

- `api/app/network_policy.py`, `api/app/services/deployments.py`: the new
  namespace label. `api/tests/test_network_policy.py` covers it.
- `tf/deps/prometheus/prometheus.tf`: the kube-state-metrics allowlist names
  the label.
- `tf/deps/prometheus/dashboards/deployments.json`, `deployment.json`, wired in
  `tf/deps/prometheus/grafana.tf`.
- Rollout: apply `tf/deps` (allowlist and dashboards), roll out the API image,
  then run `caelus sync-network-policies` once per environment. Until then the
  database and bucket columns are empty for namespaces without the label; every
  other column works without it.
