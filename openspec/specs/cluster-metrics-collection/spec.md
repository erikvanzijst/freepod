# cluster-metrics-collection Specification

## Purpose

Scrape node, workload, and Traefik metrics into Prometheus with a single-node-tuned scrape configuration and bounded retention, keeping Prometheus itself reachable only in-cluster.

## Requirements

### Requirement: Node resource metrics

The system SHALL collect per-node CPU, memory, network, and disk metrics from
every node in the cluster via a node-exporter DaemonSet bundled with the
Prometheus deployment.

#### Scenario: Node metrics are scraped

- **WHEN** Prometheus completes a scrape cycle
- **THEN** node-exporter series (e.g. `node_cpu_seconds_total`,
  `node_memory_MemAvailable_bytes`, `node_filesystem_avail_bytes`,
  `node_network_receive_bytes_total`) are present for each node

### Requirement: Workload state metrics

The system SHALL collect Kubernetes workload state metrics via
kube-state-metrics so pod, deployment, and cronjob health is queryable.

#### Scenario: Pod and cronjob state is queryable

- **WHEN** Prometheus scrapes kube-state-metrics
- **THEN** series such as `kube_pod_container_status_waiting_reason` and
  `kube_job_status_failed` are available for alert evaluation and dashboards

### Requirement: Traefik ingress metrics

The system SHALL scrape Prometheus metrics from the self-managed Traefik so
ingress throughput and latency are collectable.

#### Scenario: Traefik exposes and is scraped for metrics

- **WHEN** Traefik is configured with its Prometheus metrics endpoint enabled
  and its Service annotated for scraping
- **THEN** Prometheus's service-endpoints discovery job scrapes Traefik and
  `traefik_*` metrics become available to dashboards

### Requirement: Single-node-tuned scrape configuration

The system SHALL apply a scrape configuration tuned for a single-node k3s
cluster that drops high-cardinality control-plane histogram buckets and
retains metrics for a bounded window.

#### Scenario: High-cardinality control-plane buckets are dropped

- **WHEN** Prometheus scrapes the apiserver/kubelet endpoints
- **THEN** high-cardinality histogram bucket families (apiserver/etcd/workqueue/
  kubeproxy `_bucket`) are dropped at ingestion to bound memory use, while
  `_count`/`_sum` series are retained

### Requirement: Prometheus is not publicly exposed

The system SHALL keep the Prometheus server reachable only as a ClusterIP
service, not exposed via ingress.

#### Scenario: Operator reaches Prometheus privately

- **WHEN** an operator needs the Prometheus UI or API
- **THEN** access is available only via `kubectl port-forward` and there is no
  public ingress route for Prometheus

### Requirement: Container usage covers sandboxed containers

The system SHALL collect per-container CPU usage
(`container_cpu_usage_seconds_total`) and memory working set
(`container_memory_working_set_bytes`) from the kubelet's resource metrics,
which report containers in a gVisor sandbox. It SHALL keep exactly one
container-level series of each per container, so usage is not double-counted.

#### Scenario: Sandboxed container under load

- **WHEN** a container in a gVisor sandbox uses CPU and memory
- **THEN** both metrics report that container's actual usage, not zero

#### Scenario: Container on the default runtime

- **WHEN** a runc container is scraped
- **THEN** both metrics report the same values cAdvisor reports for it

#### Scenario: One series per container

- **WHEN** usage is queried for one container by namespace, pod and container
- **THEN** exactly one container-level series exists for each of the two
  metrics
