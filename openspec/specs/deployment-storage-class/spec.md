# deployment-storage-class Specification

## Purpose

Decides which StorageClass a deployment's volumes are provisioned on. The class is chosen once, when the deployment is created, recorded on the deployment and never changed through the API. The platform applies it to the deployment's volumes at render time, so placement never depends on chart cooperation and never changes under an existing volume.

## Requirements

### Requirement: A deployment records its storage class

Every deployment SHALL record the StorageClass its volumes are provisioned on, or none. A deployment that records none SHALL have its volumes rendered exactly as its chart renders them. Deployments that existed before this capability SHALL record none.

#### Scenario: An existing deployment after the upgrade

- **WHEN** the platform is upgraded to this capability
- **THEN** every existing deployment records no storage class, and its next reconcile renders the same volume specs as before

#### Scenario: A new deployment by an account that names no class

- **WHEN** an account that names no class creates a deployment
- **THEN** the deployment records no storage class, and its volumes are rendered as its chart renders them

### Requirement: The class is chosen once, at creation

When a deployment is created, the platform SHALL set its storage class to the class its owning account names, or to none when the account names none. The environment SHALL NOT supply a class of its own, so dev and prod choose the same way. The owner's account decides even when an administrator creates the deployment on the owner's behalf.

#### Scenario: A flagged account

- **WHEN** an account flagged with `ceph-freepod` creates a deployment
- **THEN** the deployment records `ceph-freepod`

#### Scenario: An administrator creates for a flagged account

- **WHEN** an administrator whose own account names no class creates a deployment owned by an account flagged with `ceph-freepod`
- **THEN** the deployment records `ceph-freepod`

### Requirement: Only allowed classes are chosen

Each environment SHALL list the StorageClasses its deployments may be created on. A create whose owner names a class not on the list SHALL be refused with an error naming the class, and nothing SHALL be persisted. This keeps one environment's deployments out of another environment's pool, since every class is visible cluster-wide.

#### Scenario: A dev account flagged with the prod class

- **WHEN** an account flagged with `ceph-freepod` creates a deployment on dev, which allows only `ceph-freepod-dev`
- **THEN** the create is refused, naming `ceph-freepod`, and no deployment, release or subscription row is stored

#### Scenario: An environment that allows no class

- **WHEN** a flagged account creates a deployment on an environment whose list is empty
- **THEN** the create is refused

### Requirement: The class never changes through the API

No API, CLI or UI operation SHALL accept a storage class as input, report a deployment's storage class, or change it after creation. Updating values or vars, moving to another template version, stopping, starting and redeploying SHALL all keep the class the deployment was created with.

#### Scenario: A template upgrade

- **WHEN** an administrator moves a deployment that records `ceph-freepod` to a newer template version whose chart adds a volume
- **THEN** the deployment still records `ceph-freepod`, and the new volume is provisioned on it

#### Scenario: A create that tries to choose

- **WHEN** a create or update request carries a storage class field
- **THEN** the field has no effect on the deployment's storage class

### Requirement: An account's class is an operator setting

An account SHALL name at most one StorageClass for its future deployments, and none by default. Only an operator SHALL set it, directly in the platform database; no API, CLI or UI operation SHALL read or write it. Changing an account's class SHALL affect only deployments created afterwards.

#### Scenario: Unflagging an account

- **WHEN** an operator clears the class of an account that owns deployments recording `ceph-freepod`
- **THEN** those deployments keep `ceph-freepod`, and the account's next deployment records no storage class

### Requirement: The platform applies the class to every volume

For a deployment that records a storage class, the platform SHALL set that class on every PersistentVolumeClaim and every StatefulSet volume claim template the release renders. This SHALL override any class the chart renders itself, and SHALL hold for every chart without the chart's cooperation.

#### Scenario: A chart with a standalone claim and a database StatefulSet

- **WHEN** a deployment recording `ceph-freepod` renders a data PersistentVolumeClaim and a Postgres StatefulSet with a claim template
- **THEN** both specify `storageClassName: ceph-freepod`

#### Scenario: A chart that names its own class

- **WHEN** the chart renders `storageClassName: local-path` on a claim of a deployment recording `ceph-freepod`
- **THEN** the claim is applied with `ceph-freepod`

### Requirement: Volumes on a recorded class are single-pod

For a deployment that records a storage class, the platform SHALL request `ReadWriteOncePod` as the only access mode of every PersistentVolumeClaim and StatefulSet volume claim template the release renders. A replacement pod therefore SHALL NOT mount a volume until the pod it replaces has released it.

#### Scenario: A database pod is deleted

- **WHEN** the database pod of a deployment recording `ceph-freepod` is deleted and its replacement is created before it has terminated
- **THEN** the replacement does not start until the old pod has terminated and released the volume

### Requirement: Volumes of a deployment without a class are untouched

For a deployment that records no storage class, the platform SHALL NOT set or change the class or the access modes of any PersistentVolumeClaim or StatefulSet volume claim template, and SHALL NOT refuse its release on volume grounds.

#### Scenario: A legacy StatefulSet

- **WHEN** a deployment recording no class re-renders a StatefulSet whose live claim templates name no class
- **THEN** the rendered claim templates name no class either, and the upgrade is accepted

### Requirement: The class is applied in every render

The platform SHALL apply a deployment's storage class and access mode on every apply of its release, in a normal render and in a stopped render alike, so that the release never stops asserting fields Kubernetes does not allow to change.

#### Scenario: Stopping a deployment on Ceph

- **WHEN** a deployment recording `ceph-freepod` is stopped
- **THEN** its claims are still rendered with `ceph-freepod` and `ReadWriteOncePod`, and the stop succeeds

### Requirement: Releases that would share a single-pod volume are refused

For a deployment that records a storage class, the platform SHALL refuse to render a release in which a claim of the release is mounted by more than one pod template, or by a workload that may run more than one pod at once. It SHALL also refuse one that requests an access mode other than `ReadWriteOnce` on any claim. The reconcile SHALL fail with an error naming the claim, and nothing SHALL be applied.

#### Scenario: A CronJob mounts the app's data claim

- **WHEN** a release renders a Deployment and a CronJob that both mount the claim `app-data`
- **THEN** the reconcile fails, naming `app-data`, and the cluster is unchanged

#### Scenario: A rolling Deployment mounts a claim

- **WHEN** a release renders a Deployment with the `RollingUpdate` strategy, or more than one replica, that mounts a claim
- **THEN** the reconcile fails, naming the claim

#### Scenario: A shared-filesystem claim

- **WHEN** a release renders a claim requesting `ReadWriteMany`
- **THEN** the reconcile fails, naming the claim
