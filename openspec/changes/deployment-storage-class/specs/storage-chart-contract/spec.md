# Spec Delta

## Purpose

Defines what a product chart must do so that its volumes run on any StorageClass the platform provisions: local-path, or replicated block storage with single-pod access. The platform, not the chart, decides a deployment's class and access mode.

## ADDED Requirements

### Requirement: Placement belongs to the platform

A product chart SHALL request `ReadWriteOnce` on every claim it renders, and SHALL NOT name a StorageClass by default. The platform decides the class and access mode a claim ends up with, per deployment.

#### Scenario: Rendering a chart with its defaults

- **WHEN** a catalog chart is rendered with its default and catalog system values
- **THEN** none of its PersistentVolumeClaims or volume claim templates names a `storageClassName`, and each requests `ReadWriteOnce`

### Requirement: Each claim is mounted by one pod

Every PersistentVolumeClaim a product chart renders SHALL be mounted by exactly one pod template, belonging to a workload that runs at most one pod at a time. Containers that share a volume SHALL be in the same pod. A StatefulSet's volume claim templates meet this by giving each pod its own claim.

#### Scenario: An SFTP sidecar reads the app's data

- **WHEN** a chart exposes an app's data volume to the SSH sidecar
- **THEN** the sidecar is a container in the app's pod, not a separate workload

#### Scenario: Linting the catalog

- **WHEN** every catalog chart is rendered with its default and catalog system values
- **THEN** no claim is mounted by more than one pod template, and no workload mounting a claim renders more than one replica

### Requirement: A Deployment that mounts a claim is replaced, not rolled

A Deployment that mounts a PersistentVolumeClaim SHALL use the `Recreate` strategy, so that its old pod releases the volume before the new one needs it.

#### Scenario: Upgrading such a Deployment

- **WHEN** a Deployment that mounts a single-pod claim is upgraded
- **THEN** the old pod terminates before the new pod is created, and the new pod mounts the volume

### Requirement: Data directories start on a freshly formatted volume

A product chart's containers SHALL start on a freshly formatted volume, whose root holds a `lost+found` directory. A program that refuses a non-empty data directory SHALL use a subdirectory of the volume, or have an empty `lost+found` removed before it starts. Volumes that already hold data at their root SHALL keep being used as they are.

#### Scenario: A new Immich deployment on block storage

- **WHEN** an Immich deployment is created with a volume whose root holds an empty `lost+found`
- **THEN** its Postgres initializes a new cluster and starts

#### Scenario: An existing deployment upgrades to the fixed chart

- **WHEN** an existing Immich or OpenProject deployment, whose Postgres data is at the volume root, moves to the chart version with this fix
- **THEN** Postgres starts on its existing data, and no new cluster is initialized

#### Scenario: A volume whose lost+found holds files

- **WHEN** a filesystem check has left recovered files in `lost+found` on a volume that already holds a database
- **THEN** the files are left in place, and the database starts on its existing data
