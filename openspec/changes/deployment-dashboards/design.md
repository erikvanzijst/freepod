## Context

Every series a deployment produces names it differently: kubelet and
kube-state-metrics by namespace, Traefik by router or service name (which
begin with the namespace), the tenant database exporter by `datname`
(`dpl_` and the deployment ID as hex, `relational_storage.database_name`),
and the bucket
exporter by `dep-<deployment id>`. Prometheus holds no mapping between a
namespace and a deployment ID, and Grafana has no access to the platform
database.

## Decisions

### D1: Join on a namespace label, not on the platform database

The reconciler already labels each namespace with owner, product and
environment for exactly this purpose, so the deployment ID is one more entry
in `deployment_namespace_labels`. `label_replace` derives the bucket name
from it at query time, and matches it to the 32 hex digits a `datname` ends
in, so the database join does not depend on the `dpl_` prefix.

**Alternative rejected:** a Grafana PostgreSQL datasource on the platform
database. It would also give names and emails, but it gives Grafana read
access to the platform database for a lookup that one label answers, and the
hostname makes a better search key than either.

The label adds no series: `kube_namespace_labels` is already one series per
namespace, and this widens it.

### D2: Hostnames come from `kube_ingress_path`

Every product chart renders a networking/v1 Ingress, and kube-state-metrics
already publishes its `host`. So the picker and the fleet table need no
hostname label, and a hostname change shows up without a reconcile. App
Studio's second host (`preview-<label>.<rest>`) gives way to the main one
wherever one hostname per deployment is shown, because Grafana collapses
picker options that share a value.

The picker's option text is `<hostname> · <deployment id> · <namespace>`, so
its type-ahead finds a deployment by any of the three.

### D3: Traefik joins by service name in the fleet, by router prefix per deployment

For one deployment the namespace is known, so `router=~"<namespace>-.+"`
selects its routers exactly. That includes requests a forward-auth middleware
turned away, which never reach a service.

Across the fleet a router name cannot be split back into its namespace: the
namespace, release name and host are all hyphen-joined. Traefik names a
Kubernetes backend `<namespace>-<service>-<port>@kubernetes`, though, and
removing the port leaves exactly `kube_service_info`'s namespace and service.
The fleet joins on that, so it counts requests that reached a backend.
kube-state-metrics reports a named Ingress port as `0`, which is why the join
uses the Service rather than `kube_ingress_path`'s port.

### D4: Only what is collected today

- **PVC usage is not measurable.** local-path provisions hostPath volumes,
  which kubelet reports no volume statistics for, and a `local` volume would
  report the whole host filesystem. Both dashboards show provisioned size,
  labelled as such.
- **Per-query timings are not available.** pg_stat_statements is not loaded.
  `active_time / (commit + rollback)` gives mean statement time per
  transaction, and `pg_stat_activity_max_tx_duration` gives the longest open
  transaction.
- **Release markers are pod creations.** `kube_pod_created`, filtered to one
  namespace and placed by its value, marks every rollout without a pod label
  allowlist. A rescheduled pod is marked too.
- **Platform lines are opt-in.** A collapsed row line-filters the reconciler
  and worker logs by the deployment ID. That is a scan of every platform line
  in the range, so it only runs when opened.

Kubernetes events, build pod logs and per-bucket request rates are left out:
each needs a new collector or label.
