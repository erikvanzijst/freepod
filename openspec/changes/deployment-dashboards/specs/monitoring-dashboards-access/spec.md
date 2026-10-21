## ADDED Requirements

### Requirement: Deployment namespaces carry the deployment's identity

The reconciler SHALL label each deployment namespace with
`caelus.dev/deployment-id` set to the deployment's ID, alongside its owner,
product and environment, and kube-state-metrics SHALL publish that label on
`kube_namespace_labels`. The fleet-wide network policy sync SHALL re-apply it.

#### Scenario: A reconciled namespace names its deployment

- **WHEN** the reconciler applies tenant isolation to a deployment's namespace
- **THEN** the namespace carries `caelus.dev/deployment-id` with the
  deployment's ID
- **AND** `kube_namespace_labels` for that namespace carries
  `label_caelus_dev_deployment_id`

#### Scenario: Storage series join to their namespace

- **WHEN** a dashboard needs a deployment's database or bucket size by
  namespace
- **THEN** it derives the `datname` and `dep-<id>` bucket name from the
  namespace's deployment ID label, with no platform database lookup

### Requirement: Fleet deployments dashboard

The system SHALL provision a dashboard listing every deployment of an
environment, one row each, with its hostname, CPU, memory, pod network, HTTP
request rate, database size, bucket size and provisioned PVC size, each row
linking to that deployment's dashboard. It SHALL read only collected metrics.

#### Scenario: Comparing deployments

- **WHEN** an operator opens the fleet dashboard for an environment
- **THEN** each deployment of that environment is one row showing its
  resource use and storage

#### Scenario: Unmeasurable values are not presented as usage

- **WHEN** a dashboard shows PVC storage
- **THEN** it shows provisioned size and labels it as such, since local-path
  volumes report no usage

### Requirement: Single deployment dashboard

The system SHALL provision a dashboard for one deployment, selected by
hostname, deployment ID or namespace, showing its resource use, its HTTP
traffic as Traefik saw it, its database statistics and storage, and its pod
logs alongside its Traefik access lines over one time range.

#### Scenario: Finding a deployment by hostname

- **WHEN** an operator types part of a deployment's hostname, ID or namespace
  into the deployment picker
- **THEN** the matching deployment is offered

#### Scenario: Investigating one deployment

- **WHEN** an operator opens a deployment from the fleet dashboard
- **THEN** the deployment dashboard shows that deployment's pod logs and its
  Traefik access lines for the same time range
- **AND** pod creations are marked on its graphs
