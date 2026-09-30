## ADDED Requirements

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

## MODIFIED Requirements

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

## REMOVED Requirements

### Requirement: The release identifier is offered to every chart

**Reason**: Rendering is no longer each chart's decision. Its scenario for a chart that ignores the value described the exception this change removes.

**Migration**: Replaced by "Every chart renders the release identifier", which keeps the reconciler's obligation to supply the identifier and adds the obligation for every chart to render it.
