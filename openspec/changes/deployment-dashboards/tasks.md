## 1. Deployment identity on the namespace

- [x] 1.1 Add `caelus.dev/deployment-id` to `deployment_namespace_labels` and pass it from `namespace_labels`, and verify a test asserting the label and that unknown values are omitted
- [x] 1.2 Name the label in the kube-state-metrics `metricLabelsAllowlist`
- [x] 1.3 Name it as one of the labels `caelus sync-network-policies` backfills

## 2. Dashboards

- [x] 2.1 Add `deployments.json` (fleet table, totals, top 10 over time) and `deployment.json` (health, resources, HTTP, database, storage, logs, pod-creation markers), and provision both in `grafana.tf`
- [x] 2.2 Run every panel, variable and annotation query against Prometheus 3.5 and Loki 3.5 loaded with synthetic series shaped like the cluster's, and render both dashboards in Grafana 12.1 with no panel or variable errors

## 3. Rollout

- [ ] 3.1 Apply `tf/deps`, roll out the API, and run `caelus sync-network-policies` in each environment
- [ ] 3.2 Confirm the fleet table's database and bucket columns fill in, and that the picker finds a deployment by hostname and by ID
