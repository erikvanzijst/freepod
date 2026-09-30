# release-log-labeling Specification

## Purpose

How a release identifier reaches an individual log line — supplied to the chart as a system value,
rendered onto the pod template and nowhere else, and relabeled into a stream label on the log
store — so that two pods writing concurrently during a rollout remain attributable to the release
each belongs to.

## Requirements

### Requirement: Every chart renders the release identifier

The reconciler SHALL supply the release's `uuid4` to the chart on every apply, for every
product. There SHALL be no per-product condition on the platform side.

The identifier SHALL already exist and be persisted before the Helm operation begins, because the
release is created by the request that asked for the rollout. It SHALL NOT be derived from anything
observed after the fact.

Every chart a product deploys SHALL render the identifier, as set out in "A rendered identifier is
stamped on every pod of its release". Because rendering is universal, the platform
SHALL NOT keep a record of which charts render it, and SHALL NOT vary its behavior by chart.

A chart SHALL still render and apply when no identifier is supplied, such as a standalone
`helm template` or `helm lint`. In that case it SHALL emit no release label at all, rather than
an empty one.

#### Scenario: A release of any product is applied

- **WHEN** a release of any product is applied
- **THEN** its application pods carry the release identifier

#### Scenario: A chart rendered standalone

- **WHEN** a product chart is rendered with no release identifier supplied
- **THEN** the render succeeds
- **AND** no pod template carries a `caelus.dev/release-id` label

### Requirement: A rendered identifier is stamped on every pod of its release

Every chart SHALL render the identifier as the `caelus.dev/release-id` label on the pod template
of each **application** workload it creates, so that every application pod of that release
carries it.

An application workload is one that runs the product's own software. This includes auxiliary
processes of the product, such as a web frontend, a proxy in front of it, a machine-learning
worker or a media service, and Jobs that the chart runs as part of a release.

A **datastore** workload SHALL NOT carry the label. A datastore is a database or cache whose
process belongs to a third-party engine rather than to the product, such as Postgres, MySQL,
MariaDB or Valkey. The identifier changes with every release. Stamping it on a datastore would
restart that datastore on every apply, even one that only changes a var.

A pod created later in the release's life — by a node eviction, a rescheduling or a kubelet
restart — SHALL carry the same identifier without any component having to observe its creation.

The label key SHALL follow the platform's existing convention for identifiers stamped on pods,
alongside `caelus.dev/build-id`, `caelus.dev/component` and `caelus.dev/tenant`.

Every chart under the product tree SHALL be checked against this requirement automatically. A
chart with an application workload that lacks the label, or a datastore workload that carries it,
SHALL fail that check.

#### Scenario: A rollout's pods are labeled

- **WHEN** a release is applied
- **THEN** every application pod created for it carries `caelus.dev/release-id` set to that
  release's identifier

#### Scenario: A product with several application workloads

- **WHEN** a release of a product with several application workloads is applied
- **THEN** every one of those workloads' pods carries the release identifier

#### Scenario: A datastore is not restarted by a new release

- **WHEN** a new release of a product that runs a datastore is applied
- **THEN** the datastore's pod template is unchanged by the new identifier
- **AND** the datastore is not restarted on account of it

#### Scenario: A pod is replaced without a new rollout

- **WHEN** a pod of the applied release is evicted and rescheduled, with no new release applied
- **THEN** the replacement pod carries the same release identifier as the pod it replaced

#### Scenario: An atomic rollback restores the earlier release

- **WHEN** a rollout fails and Helm rolls back
- **THEN** the pods that come back carry the **earlier** release's identifier, because they are
  that release's pods

#### Scenario: A chart that omits the label

- **WHEN** a chart is added or changed so that an application workload lacks the label
- **THEN** the automated check fails, naming the chart and the workload

### Requirement: The release label is applied to the pod template, never to a selector

The release identifier SHALL be rendered through a chart helper used **only** at the pod
template's metadata.

It SHALL NOT be added to any helper that feeds a workload's `spec.selector.matchLabels`, which
is immutable on a Kubernetes Deployment and would cause every subsequent apply to fail.

It SHALL NOT be added to any helper that feeds a Service's `spec.selector`, which would cause
the Service to select only the new release's pods before they are ready, and drop traffic during
a rollout.

#### Scenario: A second rollout is applied

- **WHEN** a deployment that already has a release is applied again with a new release
  identifier
- **THEN** the apply succeeds, because no immutable selector field changed

#### Scenario: Traffic during a rollout

- **WHEN** a new release's pods are starting while the previous release's pods still serve
- **THEN** the Service continues to select the serving pods throughout

### Requirement: The release identifier is a system value a tenant cannot forge

The release identifier SHALL be supplied to the chart as a system override under the platform's
reserved `caelus` values namespace, applied after user-scoped values so that user values cannot
shadow it.

A tenant SHALL NOT be able to set, override or influence the release identifier through user
values, the deployment form, or any request field.

#### Scenario: A tenant supplies a conflicting value

- **WHEN** a tenant submits user values that attempt to set the release identifier
- **THEN** the rendered pod carries the platform's identifier, not the tenant's

### Requirement: The release identifier is a Loki stream label

The log collector SHALL relabel the `caelus.dev/release-id` pod label into a Loki **stream
label**, so that a query for one release is an index lookup rather than a scan of every line the
deployment has produced.

It SHALL NOT be carried as structured metadata. The usual reason to prefer structured metadata —
avoiding stream multiplication from a high-cardinality field — does not apply, because `pod` is
already a stream label and the release identifier is constant within a pod. It is functionally
dependent on a label that already exists, so promoting it widens each existing series without
creating new ones.

#### Scenario: Logs are queryable by release

- **WHEN** a pod carrying a release identifier writes a line
- **THEN** the line is retrievable by a selector naming that release, without scanning the
  deployment's other releases

#### Scenario: Two releases write concurrently

- **WHEN** a rollout is in progress and pods of two releases are writing at the same time
- **THEN** a query naming one release returns only that release's lines, with no interleaving
  from the other

#### Scenario: A release's pods have been deleted

- **WHEN** a rollout failed, was rolled back, and its pods were deleted
- **THEN** that release's lines remain retrievable by its identifier

### Requirement: Every returned line is attributable to a release

A log line returned from the store SHALL carry the identifier of the release that produced it,
so that a reader following a deployment across a rollout can tell which release each line came
from without issuing a second query.

#### Scenario: A reader observes a rollover

- **WHEN** a reader is following a deployment and a new release becomes live
- **THEN** the lines from before and after the rollover are individually attributable to their
  respective releases
