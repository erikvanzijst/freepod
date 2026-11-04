# Proposal

## Why

`custom` and App Studio run code Freepod has never seen: a tenant's own build,
and whatever App Studio's agent installs and runs. Today those containers run
on runc and share the node's kernel. User namespaces and the default seccomp
profile narrow that, but a single kernel exploit still escapes the container
onto a node holding other tenants' workloads and secrets. gVisor puts a
user-space kernel between the workload and the host, so an escape needs a
sandbox bug and then a host-kernel bug reachable through gVisor's narrow
seccomp filter. Usage metering already covers sandboxed pods, so they can
move now without being billed as idle.

## What Changes

- A cluster-wide `gvisor` RuntimeClass, managed in Terraform. It names the
  runsc handler, schedules onto the tenant node pool, and declares the
  sandbox's fixed overhead so the scheduler and limits account for it.
- A new `runtimeClassName` system value in the `custom` and App Studio charts,
  set from the catalog the same way `nodePool` is. The catalog sets it to
  `gvisor` for both products. Empty keeps the pod on the default runtime.
- **BREAKING (scheduling):** sandboxed pods **require** the tenant node pool.
  The `custom` app and App Studio no longer fall back to another node while
  the pool has no schedulable node; they stay Pending until it returns.
- Sandboxed pods omit `hostUsers: false`, which runsc does not support. gVisor
  runs each sandbox in its own user namespace under a seccomp filter instead.
  Pods on the default runtime keep `hostUsers: false`.
- The tenant node's runsc install and containerd registration are documented
  next to the RuntimeClass, because node OS configuration is not managed by
  Terraform.
- Existing `custom` and App Studio deployments move to the new chart versions,
  dev first, then prod.

Out of scope: builds (they work under gVisor but are ~3.5× slower on cold
builds and need a cgroup-v1 path in the build meter), curated product charts,
and platform workloads such as the tenant database cluster.

## Capabilities

### New Capabilities

- `tenant-sandbox-runtime`: which workloads run under the sandboxed runtime,
  how a chart opts in, where sandboxed pods may schedule, and the pod-spec
  constraints that runtime imposes.

### Modified Capabilities

- `cluster-metrics-collection`: per-container CPU and memory usage is
  collected from a source that reports sandboxed containers, not only
  containers with their own cgroup.

## Impact

- **Terraform:** `tf/deps` gains the RuntimeClass (cluster-scoped); applied
  with a targeted apply.
- **Charts:** `products/custom/chart` (template, values, values schema,
  version bump) and `products/appstudio/chart` (template, values, version
  bump).
- **Catalog:** `products/catalog/custom/custom.yaml` and
  `products/catalog/appstudio/appstudio.yaml` gain the system value and the
  new chart versions.
- **Tests:** `api/tests/test_custom_chart.py` and
  `api/tests/test_appstudio_chart.py` cover both runtimes.
- **Docs:** `tf/deps/README.md` (node setup and the RuntimeClass), the
  `custom` README's pod description.
- **Operations:** during a tenant-node outage, `custom` apps and App Studio are
  down rather than moved to the control-plane node. The sandbox's own memory
  (15–22 MiB per pod, measured) is counted at pod level and not billed to any
  container. Under gVisor only a pod's total CPU limit is enforced, not each
  container's.
