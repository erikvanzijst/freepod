## Purpose

How the reconciler brings a deployment's cluster state to its desired power: rendering a release in which nothing runs through the platform post-renderer, recording the outcome, and the edge behavior that keeps a stopped or starting app answering with 503 instead of 404.

## ADDED Requirements

### Requirement: Every reconcile renders the desired power

Every reconcile that applies a deployment's Helm release SHALL render it in the deployment's desired power. A desired power of `paused` or `stopped` SHALL produce a suspended render, in which nothing runs; `running` SHALL produce a normal render. This SHALL hold whatever requested the reconcile, so that a release applied to a stopped deployment stays stopped.

#### Scenario: An owner edits a stopped deployment

- **WHEN** the owner updates the values of a stopped deployment
- **THEN** the new release is applied with a suspended render, and the deployment stays stopped

#### Scenario: A platform rollout reaches a stopped deployment

- **WHEN** an operator moves a stopped deployment to a new template version
- **THEN** the release is applied with a suspended render, and no workload starts

### Requirement: A suspended render runs no workload

A suspended render SHALL set every Deployment and StatefulSet of the release to zero replicas and suspend every Job and CronJob. It SHALL omit every HorizontalPodAutoscaler and every bare Pod. It SHALL leave PersistentVolumeClaims, Secrets, ConfigMaps and Services as the chart renders them.

#### Scenario: A product with an in-chart database

- **WHEN** a deployment whose chart renders an app Deployment and a database StatefulSet is stopped
- **THEN** both are at zero replicas and their PersistentVolumeClaims remain

#### Scenario: Starting restores the chart's replica counts

- **WHEN** the deployment is started
- **THEN** every workload runs with the replica count its chart renders

### Requirement: A suspended render runs no Helm hooks

A suspended render SHALL omit every document that Helm treats as a hook. A hook may need the running app, and one that fails against a scaled-down release would make the atomic apply roll the stop back.

#### Scenario: A post-upgrade hook that calls the app

- **WHEN** a deployment whose chart has a post-upgrade hook Job that calls the app's Service is stopped
- **THEN** the stop succeeds and the hook does not run

### Requirement: A suspended render routes the hostname to the activator

A suspended render SHALL point every Ingress rule for the deployment's own hostname at a platform-owned `ExternalName` Service in the release that resolves to the environment's activator. It SHALL keep each Ingress's annotations, middlewares and TLS settings, so that edge authentication still runs before the activator. Rules for other hostnames SHALL be left unchanged.

#### Scenario: A visitor reaches a stopped app

- **WHEN** a visitor requests a stopped deployment's hostname
- **THEN** the request is answered by the activator

#### Scenario: An auth-protected app is stopped

- **WHEN** a stopped deployment has app authentication enabled
- **THEN** a visitor who is not signed in is sent to sign in before the activator answers

#### Scenario: A host with several backends

- **WHEN** a chart routes different paths of the deployment's hostname to different Services
- **THEN** every path of that hostname is answered by the activator while the deployment is stopped

#### Scenario: App Studio's preview host

- **WHEN** an App Studio deployment is stopped
- **THEN** its `preview-` hostname's Ingress is not routed to the activator

### Requirement: A normal render carries nothing of a suspended one

A render with running power SHALL produce the chart's manifests exactly as the post-renderer's other steps leave them. Starting a deployment SHALL remove the activator Service and restore every Ingress backend the chart renders.

#### Scenario: After starting

- **WHEN** a started deployment's reconcile succeeds
- **THEN** its Ingress backends are the chart's own and the release contains no activator Service

### Requirement: The reconciler records the power outcome

On success, a reconcile SHALL point the deployment's applied power at its desired power and record the desired power row's end time. On failure, it SHALL leave the applied power unchanged, record the error on the desired power row, and set the deployment's status to `error` with the failure as its last error, as a failed rollout does.

#### Scenario: A stop is applied

- **WHEN** a stop reconcile succeeds
- **THEN** the deployment's applied power equals its desired power and its status is `ready`

#### Scenario: A stop fails

- **WHEN** a stop reconcile fails and Helm rolls back
- **THEN** the applied power still names the running power, the status is `error`, and the power row records the error

### Requirement: A power change and a release apply in one render

When a deployment has both a release and a power change waiting to be applied, the reconciler SHALL apply them in one Helm run, and SHALL record both outcomes from it.

#### Scenario: Both applied together

- **WHEN** a reconcile finds a new desired release and a new desired power
- **THEN** one Helm run applies the release in the desired power, and both the release and the power row record its outcome

### Requirement: Routers without endpoints answer 503

The edge SHALL keep the route of an Ingress whose Service has no ready endpoints, and SHALL answer requests on it with `503` after running its middlewares, instead of dropping the route and answering `404`. This SHALL hold for every Ingress on the cluster.

#### Scenario: A started app still booting

- **WHEN** a started deployment's Ingress points back at its Service before its pods are ready
- **THEN** a request to its hostname is answered with `503`, not `404`

#### Scenario: A crashed app

- **WHEN** a running deployment has no ready pods
- **THEN** a request to its hostname is answered with `503`
