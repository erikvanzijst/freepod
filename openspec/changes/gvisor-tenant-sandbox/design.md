# Design

## Context

- **Runtime on the node:** the tenant node already has runsc installed and
  registered with containerd as the `runsc` handler (pinned release, systemd
  cgroups). Every other node runs runc only. This configuration lives on the
  node; Terraform does not manage node OS state.
- **RuntimeClass:** a `gvisor` RuntimeClass exists in the cluster, created by
  hand for testing. Nothing references it yet.
- **Charts:** `custom` (a Deployment: the app plus the SSH sidecar, with
  `shareProcessNamespace: true`) and App Studio (a StatefulSet: `chrome` and
  `opencode` containers, two PVCs) both set `hostUsers: false`. Both *prefer*
  the tenant pool through the `nodePool` system value, a toleration plus a
  preferred node affinity.
- **Metering:** container usage already comes from the kubelet's resource
  metrics, which report sandboxed containers correctly (see the
  `cluster-metrics-collection` delta). The requirement records that
  dependency; no further metering work is needed.
- **Measured on the tenant node:**
  - Sandbox overhead is 15–22 MiB per pod, charged to the pod's cgroup.
  - NetworkPolicy is enforced in both directions.
  - Logs reach Loki with normal labels.
  - A shared PID namespace works: a sidecar can see the app container's
    processes and read its root through `/proc/<pid>/root`.
  - CPU limits are enforced per pod, not per container.

## Goals / Non-Goals

**Goals:**

- One switch per product, in the catalog, that moves its tenant pods onto the
  sandbox and can move them back.
- Sandboxed pods can only ever land on a node that has the runtime.

**Non-Goals:**

- Per-deployment runtime choice. The runtime is a product property.
- Billing the sandbox's own overhead.
- Enforcing per-container CPU limits inside a sandbox.

## Decisions

### D1: The RuntimeClass lives in `tf/deps`, as a manifest

The RuntimeClass is cluster-scoped and shared by dev and prod, like the
cluster's other dependencies. It goes in a small `tf/deps/sandbox` module as a
`kubernetes_manifest`, the same pattern `tf/deps/system` uses for its
cluster-scoped objects. A manifest carries `overhead` and `scheduling`
verbatim, with no dependence on how a typed resource models them.

The hand-made object is **imported**, not recreated, so nothing ever sees the
RuntimeClass missing.

*Alternative:* `tf/app`, per environment. Rejected: two workspaces cannot both
own one cluster-scoped name.

### D2: The runtime is a catalog system value, not a reconciler default

`runtimeClassName` follows `nodePool` exactly:
- an empty default in the chart's `values.yaml`;
- an entry in the chart's values schema where one exists;
- set in the product's `template.system_values`, absent from the
  tenant-facing schema.

That keeps the decision in the catalog, which is where product rollout already
happens, and makes reverting it a catalog change plus an upgrade.

*Alternative:* the reconciler injects a runtime for every pod of chosen
products. Rejected: it adds a second place that shapes pod specs, and charts
would render differently under Helm than under the reconciler.

### D3: The pool requirement comes from the RuntimeClass, not the chart

The RuntimeClass's `scheduling.nodeSelector` and toleration are merged into
every pod that uses it at admission. That makes the tenant pool a hard
requirement for sandboxed pods, without the chart having to know which nodes
carry the runtime. The charts keep their existing `nodePool` preference; it
becomes redundant for sandboxed pods but is still what places the pod when
`runtimeClassName` is empty.

*Alternative:* install runsc on every node and keep the preferred affinity.
Rejected: it puts sandboxed tenant code back on the control-plane node during
a tenant-node outage, which is the placement this work is trying to avoid, and
it costs CPU on the smallest node.

### D4: `hostUsers: false` is rendered only when `runtimeClassName` is empty

runsc does not implement the ID-mapped mounts that pod user namespaces need,
so a pod that sets both fails to start. The condition is "no runtime class
set", not "runtime class is gvisor", so any future runtime starts from the
safe side: user namespaces stay on until a chart is shown to need them off.

*Alternative:* gVisor's proposed opt-in annotation for user namespaces.
Rejected: not released. Revisit once runsc supports `hostUsers: false`.

### D5: Overhead of 32 MiB and 10m CPU

Measured idle overhead is 15–22 MiB. 32 MiB leaves headroom for the Sentry
growing under load without re-measuring per product. The overhead also raises
the pod-level memory limit, so the app keeps its full container limit rather
than sharing it with the sandbox. CPU is set low because the Sentry's CPU is
spent on the workload's own system calls, which the containers' usage already
counts.

### D6: Chart versions

- `custom` 0.15.0 → 0.16.0: a scheduling and runtime change, not a fix.
- App Studio 0.2.19 → 0.2.20, following that chart's patch-level history.

Existing versions are never re-pushed.

### D7: Node setup is documented next to the RuntimeClass

The runsc install, containerd template, runsc config, upgrade and rollback
steps go in `tf/deps/README.md`. That's where an operator rebuilding the
tenant node, or wondering why `gvisor` pods are Pending, will look first.

## Risks / Trade-offs

- **Tenant-node outage takes `custom` and App Studio down.** They no longer
  fall back to the control-plane node. → Accepted; it's the point of D3. The
  README's operating notes say so. Planned node maintenance becomes planned
  downtime for these products.
- **An app fails under gVisor** (no io_uring, unsupported syscalls, file-I/O
  heavy workloads slower). → Dev rollout exercises a real `custom` app and App
  Studio. A product-wide revert is the catalog value set back to empty plus an
  upgrade. Per-deployment opt-out is not offered.
- **App Studio's existing PVC data under a different user model.** Volumes
  were written through ID-mapped mounts, which store container-side UIDs on
  disk, so files should read the same without the user namespace. → Verified
  on a dev App Studio instance with existing projects before prod.
- **runsc upgrades are manual.** → The README covers the procedure. Running
  sandboxes keep the binary they started with until their pod restarts.
- **Some dashboard panels go blank for sandboxed pods.** Panels built on
  cAdvisor-only families (`container_memory_rss`, throttling) have nothing to
  show. → Display only; metering does not use them.
- **The SSH sidecar can take CPU from the app.** CPU limits are enforced only
  per pod. → Accepted. The pod as a whole stays bounded.

## Migration Plan

1. **RuntimeClass:** add `tf/deps/sandbox` and import the existing
   RuntimeClass. A targeted apply should then only add the overhead.
2. **Charts:** publish `custom` 0.16.0 and App Studio 0.2.20. Neither renders
   a `runtimeClassName` until the catalog sets one.
3. **Dev:** apply the catalog to dev and upgrade dev's `custom` and App Studio
   deployments. Verify:
   - the app serves;
   - `freepod shell` (app-container session), `cp` and `log` work;
   - the database is reachable through PgBouncer;
   - App Studio's agent can `apt install` and its existing projects still open;
   - OpenCost reports the pods' usage.
4. **Prod:** apply the catalog and upgrade every prod `custom` and App Studio
   deployment.

**Rollback:** set `runtimeClassName` back to empty in the catalog and upgrade.
Pods return to runc with `hostUsers: false`. The RuntimeClass and the node
runtime can stay in place unused.
