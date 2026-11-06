## Purpose

How the reconciler brings a deployment's cluster state to its desired power:
- rendering, through the platform post-renderer, a release in which nothing runs;
- making sure nothing runs after it is applied;
- recording the outcome;
- the rules on catalog charts and at the edge that keep a stopped or starting app answering with 503 instead of failing or answering 404.

## ADDED Requirements

### Requirement: Every reconcile renders the desired power

Every reconcile that applies a deployment's Helm release SHALL render it in the deployment's desired power: a stopped render for `stopped`, a normal render for `running`. This SHALL hold whatever requested the reconcile, so that a release applied to a stopped deployment stays stopped.

#### Scenario: An owner edits a stopped deployment

- **WHEN** the owner updates the values of a stopped deployment
- **THEN** the new release is applied with a stopped render, and the deployment stays stopped

#### Scenario: A platform rollout reaches a stopped deployment

- **WHEN** an operator moves a stopped deployment to a new template version
- **THEN** the release is applied with a stopped render, no workload starts, and the release is recorded as succeeded

### Requirement: A stopped render runs no workload

A stopped render SHALL:
- set `spec.replicas` to `0` on every Deployment and StatefulSet of the release, so that Helm owns the field at 0;
- set `spec.suspend` to true on every Job and CronJob;
- omit every HorizontalPodAutoscaler and every bare Pod.

It SHALL leave PersistentVolumeClaims, Secrets, ConfigMaps and the chart's Services as the chart renders them. The platform's other post-render steps, such as the egress gate, SHALL apply as in a normal render.

#### Scenario: A product with an in-chart database

- **WHEN** a deployment whose chart renders an app Deployment and a database StatefulSet is stopped
- **THEN** both are at zero replicas and their PersistentVolumeClaims remain

#### Scenario: Starting restores the chart's replica counts

- **WHEN** the deployment is started
- **THEN** every workload runs with the replica count its chart renders

### Requirement: Nothing runs once a stop is applied

After a stopped render has been applied successfully, the reconciler SHALL scale to zero every Deployment and StatefulSet in the deployment's namespace whose replica count is above zero, whatever set it. A failure to do so SHALL fail the reconcile as a failed Helm apply does.

#### Scenario: A workload scaled up while the stop was applied

- **WHEN** something outside Helm scales a workload of the deployment back up while its stop is being applied
- **THEN** after the stop reconcile succeeds, that workload is at zero replicas

### Requirement: Catalog charts render no Helm hooks

No catalog chart SHALL render a document that Helm treats as a hook. A hook runs on every install and upgrade, including those applied to a deployment at zero replicas. A hook that needs the app would then fail and make the atomic apply roll back. The platform's chart tests SHALL fail for any catalog chart that renders a hook.

#### Scenario: A chart adds a hook

- **WHEN** a catalog chart renders a document with a `helm.sh/hook` annotation
- **THEN** the chart tests fail

#### Scenario: Stopping a product that needs a first-run action

- **WHEN** a Vaultwarden deployment is stopped
- **THEN** the stop succeeds and nothing runs against the stopped app

### Requirement: A stopped render routes the hostname to the parking page

A stopped render SHALL point every backend of every Ingress rule for the deployment's own hostname, matched case-insensitively, at a platform-owned `ExternalName` Service in the release that resolves to the environment's API. Rules for other hostnames SHALL be left unchanged.

#### Scenario: A visitor reaches a stopped app

- **WHEN** a visitor requests a stopped deployment's hostname
- **THEN** the request is answered by the parking page

#### Scenario: A host with several backends

- **WHEN** a chart routes different paths of the deployment's hostname to different Services
- **THEN** every path of that hostname is answered by the parking page while the deployment is stopped

#### Scenario: App Studio's preview host

- **WHEN** an App Studio deployment is stopped
- **THEN** its `preview-` hostname's Ingress keeps its chart backends and answers `503`

#### Scenario: The parking address is not configured

- **WHEN** a stopped render is needed and the platform has no parking address configured
- **THEN** the reconcile fails instead of rendering an Ingress that points nowhere

### Requirement: A rerouted Ingress keeps its edge settings

A stopped render SHALL keep each Ingress's annotations, router middlewares and TLS settings, so that edge authentication still runs before the parking page.

#### Scenario: An auth-protected app is stopped

- **WHEN** a stopped deployment has app authentication enabled
- **THEN** a visitor who is not signed in is sent to sign in before the parking page answers

### Requirement: The parking Service's name is reserved

The name of the parking `ExternalName` Service SHALL be reserved for the platform. The platform's chart tests SHALL fail for any catalog chart that renders a Service with that name.

#### Scenario: A chart uses the reserved name

- **WHEN** a catalog chart renders a Service named like the release's parking Service
- **THEN** the chart tests fail

### Requirement: A normal render carries nothing of a stopped one

A render with running power SHALL produce the chart's manifests exactly as the post-renderer's other steps leave them. Starting a deployment SHALL remove the parking Service and restore every Ingress backend and replica count the chart renders.

#### Scenario: After starting

- **WHEN** a started deployment's reconcile succeeds
- **THEN** its Ingress backends are the chart's own, its workloads have the chart's replica counts, and the release contains no parking Service

### Requirement: The reconciler records the power outcome

On success, a reconcile SHALL point the deployment's applied power at its desired power and record the desired power row's end time. On failure, it SHALL, in one transaction:
- leave the applied power unchanged;
- record the end time and the error on the desired power row;
- point the deployment's desired power back at its applied power;
- set the deployment's status to `error` with the failure as its last error, as a failed rollout does.

#### Scenario: A stop is applied

- **WHEN** a stop reconcile succeeds
- **THEN** the deployment's applied power equals its desired power and its status is `ready`

#### Scenario: A stop fails

- **WHEN** a stop reconcile fails and Helm rolls back
- **THEN** the applied power still names the running power, the desired power names it too, the status is `error`, and the power row records the error

### Requirement: A failed power change is never applied later

A reconcile SHALL NOT apply a power change whose reconcile has already failed, and SHALL NOT write a failed power row's outcome again. The owner recovers a deployment in `error` by deploying, which renders it in the power it was running.

#### Scenario: Deploying after a failed stop

- **WHEN** a stop has failed and the owner deploys to recover the deployment
- **THEN** the release is applied with a normal render, the deployment ends `ready` and running, and the failed power row's end time and error are unchanged

#### Scenario: Deploying after a failed start

- **WHEN** a start of a stopped deployment has failed and the owner deploys to recover it
- **THEN** the release is applied with a stopped render and the deployment ends `ready` and stopped

### Requirement: A power change and a release apply in one render

When a deployment has both a release and a power change waiting to be applied, the reconciler SHALL apply them in one Helm run, and SHALL record both outcomes from it.

#### Scenario: Both applied together

- **WHEN** a reconcile finds a new desired release and a new desired power
- **THEN** one Helm run applies the release in the desired power, and both the release and the power row record its outcome

### Requirement: Routers without endpoints answer 503

The edge SHALL keep the route of an Ingress whose Service has no ready endpoints. It SHALL run the route's middlewares and answer `503`, instead of dropping the route and answering `404`. This SHALL hold for every Ingress on the cluster.

#### Scenario: A started app still booting

- **WHEN** a started deployment's Ingress points back at its Service before its pods are ready
- **THEN** a request to its hostname is answered with `503`, not `404`

#### Scenario: A crashed app

- **WHEN** a running deployment has no ready pods
- **THEN** a request to its hostname is answered with `503`
