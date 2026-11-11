# Spec Delta

## MODIFIED Requirements

### Requirement: A stopped render runs no workload

A stopped render SHALL:
- set `spec.replicas` to `0` on every Deployment and StatefulSet of the release, so that Helm owns the field at 0;
- set `spec.suspend` to true on every Job and CronJob;
- omit every HorizontalPodAutoscaler and every bare Pod.

It SHALL leave PersistentVolumeClaims, Secrets, ConfigMaps and the chart's Services as the chart renders them, apart from what the platform's other post-render steps change. Those steps, such as the egress gate and the deployment's storage class, SHALL apply as in a normal render.

#### Scenario: A product with an in-chart database

- **WHEN** a deployment whose chart renders an app Deployment and a database StatefulSet is stopped
- **THEN** both are at zero replicas and their PersistentVolumeClaims remain

#### Scenario: Starting restores the chart's replica counts

- **WHEN** the deployment is started
- **THEN** every workload runs with the replica count its chart renders

#### Scenario: Stopping a deployment that records a storage class

- **WHEN** a deployment recording `ceph-freepod` is stopped
- **THEN** its PersistentVolumeClaims and volume claim templates keep `ceph-freepod` and `ReadWriteOncePod`, exactly as in its normal render
