# tenant-sandbox-runtime Specification

## Purpose

Runs workloads that execute tenant-supplied or agent-driven code under a
sandboxed container runtime, so a container escape needs more than one host
kernel bug, and defines how charts opt in and where sandboxed pods schedule.

## Requirements

### Requirement: Sandboxed runtime class

The cluster SHALL provide a RuntimeClass named `gvisor` whose handler is the
gVisor runtime. It SHALL declare a fixed per-pod overhead for the sandbox's own
memory and CPU, so scheduling and the pod's resource bounds include it.

#### Scenario: A pod requests the sandboxed runtime

- **WHEN** a pod sets `runtimeClassName: gvisor`
- **THEN** its containers run inside a gVisor sandbox, and the kernel they see
  reports itself as gVisor rather than the host kernel

#### Scenario: Overhead is added to the pod

- **WHEN** a pod using the `gvisor` RuntimeClass is admitted
- **THEN** its `spec.overhead` carries the RuntimeClass's fixed overhead

### Requirement: Sandboxed pods run only on the tenant node pool

The `gvisor` RuntimeClass SHALL restrict its pods to nodes labeled
`caelus.dev/node-pool=tenant` and SHALL tolerate that pool's taint. A sandboxed
pod SHALL NOT be scheduled onto any other node, including when the pool has no
schedulable node.

#### Scenario: Pool available

- **WHEN** a sandboxed pod is created and a tenant-pool node is schedulable
- **THEN** the pod is scheduled onto a tenant-pool node

#### Scenario: Pool unavailable

- **WHEN** a sandboxed pod is created and no tenant-pool node is schedulable
- **THEN** the pod stays Pending rather than being scheduled onto another node

### Requirement: Charts opt in through a system value

A chart that supports the sandboxed runtime SHALL take a `runtimeClassName`
system value and render it as the pod's `runtimeClassName`. The value SHALL be
set only by the product's catalog entry and SHALL NOT be tenant-settable. When
it is empty, the pod SHALL use the cluster's default runtime.

#### Scenario: Catalog selects the sandbox

- **WHEN** the catalog entry sets `runtimeClassName: gvisor`
- **THEN** the chart's tenant pods render `runtimeClassName: gvisor`

#### Scenario: No runtime selected

- **WHEN** `runtimeClassName` is empty
- **THEN** the chart's pods render no `runtimeClassName` and run on the default
  runtime

#### Scenario: A tenant cannot choose the runtime

- **WHEN** a tenant supplies `runtimeClassName` in their deployment values
- **THEN** the value is rejected by the tenant-facing values schema

### Requirement: User namespaces on the default runtime only

A chart SHALL render `hostUsers: false` on its tenant pods when they run on the
default runtime, and SHALL omit it when they run on the sandboxed runtime,
which does not support pod user namespaces.

#### Scenario: Default runtime

- **WHEN** a pod renders without a `runtimeClassName`
- **THEN** it sets `hostUsers: false`

#### Scenario: Sandboxed runtime

- **WHEN** a pod renders with `runtimeClassName: gvisor`
- **THEN** it does not set `hostUsers`

### Requirement: Sandboxed pods keep a disk-backed /tmp

A chart SHALL mount a disk-backed volume at `/tmp` in every container that runs
tenant code when the pod runs on the sandboxed runtime, which otherwise serves
`/tmp` from memory. Files there SHALL count toward the pod's ephemeral storage,
not its memory, as they do on the default runtime.

#### Scenario: A large upload is staged in /tmp

- **WHEN** a sandboxed app writes more data to `/tmp` than its memory limit
- **THEN** the write succeeds and the pod is not OOM-killed

#### Scenario: /tmp counts as ephemeral storage

- **WHEN** a sandboxed app keeps more data in `/tmp` than its ephemeral-storage
  limit
- **THEN** the pod is evicted for ephemeral storage, as it would be on the
  default runtime

#### Scenario: Default runtime is unchanged

- **WHEN** a pod renders without a `runtimeClassName`
- **THEN** no volume is mounted at `/tmp`

### Requirement: Tenant-code products run sandboxed

The `custom` product and App Studio SHALL run their tenant pods under the
`gvisor` runtime. Builds, curated product charts, and platform workloads SHALL
remain on the default runtime.

#### Scenario: A custom app is deployed

- **WHEN** a `custom` deployment is provisioned or upgraded
- **THEN** its app pod, including the SSH sidecar, runs under `gvisor`

#### Scenario: An App Studio instance is deployed

- **WHEN** an App Studio deployment is provisioned or upgraded
- **THEN** its pod runs under `gvisor`

#### Scenario: Other workloads are unchanged

- **WHEN** a build Job, a curated product, or the tenant database cluster runs
- **THEN** its pods have no `runtimeClassName`

### Requirement: Sandboxed pods keep network isolation

A sandboxed pod SHALL be subject to the same NetworkPolicy enforcement as a pod
on the default runtime, in both directions.

#### Scenario: Denied egress

- **WHEN** the deployment's NetworkPolicy denies a destination
- **THEN** a connection from the sandboxed pod to it fails

#### Scenario: Denied ingress

- **WHEN** the deployment's NetworkPolicy does not admit a source
- **THEN** a connection from that source to the sandboxed pod fails
