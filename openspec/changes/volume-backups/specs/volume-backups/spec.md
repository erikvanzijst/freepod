# Spec Delta

## Purpose

Keeps an encrypted copy of the platform's replicated volumes, and of the Secrets they cannot be used without, outside the storage cluster: taken nightly, kept for a bounded time, purged after deletion, watched for staleness, and restorable by an operator.

## ADDED Requirements

### Requirement: Nightly backup of replicated volumes

The platform SHALL back up, once a day, the data of every volume provisioned on a replicated (Ceph) StorageClass, in every namespace except the cluster's system namespace and the backup system's own. Volumes on `local-path` SHALL be skipped without a warning. The copy SHALL be stored in an object store that does not depend on the storage cluster.

#### Scenario: A deployment on Ceph

- **WHEN** the nightly backup runs and a namespace holds claims on a Ceph StorageClass
- **THEN** the backup holds the data of each of those claims, and a restore of any of them yields the files, owners and modes the claim held when its snapshot was taken

#### Scenario: A deployment on local-path

- **WHEN** the nightly backup runs and a namespace holds only `local-path` claims
- **THEN** no volume data is copied for it, and the backup reports no warning for those claims

#### Scenario: A deployment created during the day

- **WHEN** a deployment on Ceph is created after one nightly backup
- **THEN** the next nightly backup includes its volumes without any configuration change

### Requirement: Only what cannot be rebuilt is kept

Besides volume data, a backup SHALL keep each backed-up namespace's claims and its Secrets, and nothing else. Secrets owned by Helm's release history SHALL be excluded. Everything else in a namespace SHALL be left to the platform to rebuild.

#### Scenario: A chart-generated database password

- **WHEN** a chart generated a database password at install time and keeps it only in a Secret
- **THEN** that Secret is in the namespace's nightly backup

#### Scenario: Workloads and routing

- **WHEN** a namespace holds Deployments, Services, Ingresses and Helm release records
- **THEN** none of them is in the backup

### Requirement: Backups are encrypted at rest

Volume data SHALL be encrypted inside the cluster before upload, with a key the object store never receives. Every other object a backup writes SHALL be stored encrypted with a customer-provided key that the object store does not retain. Neither SHALL be readable from the bucket without the platform's keys.

#### Scenario: Reading the bucket with storage credentials only

- **WHEN** someone holding only the bucket's access keys reads a backup's objects
- **THEN** volume data reads as ciphertext, and every other backup object is refused

### Requirement: Fourteen-day retention

Each backup SHALL be deleted 14 days after it is taken, together with its volume snapshots in the backup repository. Data that no remaining backup references SHALL be removed from the bucket by the repository's maintenance, which SHALL run at least daily.

#### Scenario: An old backup

- **WHEN** a backup is 14 days old
- **THEN** it is deleted, and data referenced only by it is removed from the bucket after the following maintenance cycles

### Requirement: Deleted deployments leave the backups

After a deployment is deleted, no new backup SHALL include it, and every trace of it SHALL be gone from the backup system once the last backup that included it has expired: its volume data, its Secrets, its backup repository, and the objects and records that name its namespace. This SHALL happen without operator action.

#### Scenario: A tenant deletes a deployment

- **WHEN** a deployment with Ceph volumes is deleted
- **THEN** its namespace is absent from every later backup, and within the bound stated in the Terms after the deletion, the bucket and the cluster hold no object or record naming its namespace

### Requirement: Stale backups raise an alert

The platform SHALL raise a critical alert when no nightly backup has completed successfully for 26 hours, or when no successful nightly backup is reported at all. A backup in which any volume failed SHALL NOT count as successful.

#### Scenario: A nightly backup partly fails

- **WHEN** one volume's upload fails and no later nightly backup succeeds
- **THEN** `BackupTooOld` fires 26 hours after the last fully successful backup

#### Scenario: The backup system is down

- **WHEN** the backup system reports no successful nightly backup
- **THEN** `BackupTooOld` fires

### Requirement: Backups do not starve the cluster

At most one volume per node SHALL be uploading and at most one more SHALL be prepared for upload at any moment. Each upload SHALL run with a bounded memory limit, so an oversized volume fails its own backup rather than exhausting a node.

#### Scenario: Many volumes in one backup

- **WHEN** a nightly backup covers more volumes than the concurrency cap
- **THEN** the volumes are uploaded in turn, and no more than the capped number of data-mover pods exists at once

### Requirement: Operator restore for disaster recovery

An operator SHALL be able to restore a deployment's volumes and Secrets from any retained backup into the deployment's own namespace, after the platform has recreated the deployment stopped. Restores SHALL NOT be offered to tenants. The procedure SHALL be documented and rehearsed.

#### Scenario: Restoring a deployment

- **WHEN** an operator restores a stopped deployment from a retained backup and then starts it
- **THEN** its claims hold the backed-up data, its Secrets hold the backed-up values, and the application starts against its restored database
