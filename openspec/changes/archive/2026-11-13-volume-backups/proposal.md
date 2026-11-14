# Proposal

## Why

Volumes on the replicated Ceph pools have no copy outside Ceph. Three replicas
survive a lost disk or node, but not a lost pool, a bad upgrade, or data that is
deleted or corrupted and then replicated. Local-path volumes are covered by
backups of the nodes themselves; Ceph volumes are not inside any node, so
nothing backs them up. Tenants move to Ceph from here on, so the gap grows with
every migration.

## What Changes

- Every night, the platform backs up every volume on a Ceph StorageClass, in
  every namespace, to an S3 bucket outside the Ceph cluster.
  - Each volume is snapshotted, and the snapshot's files are uploaded
    incrementally and encrypted before they leave the cluster.
  - Alongside each volume, the backup keeps the Kubernetes objects that cannot
    be rebuilt: the claims, and the Secrets that charts generate in the cluster
    (database passwords, signing keys). Everything else is rebuilt from
    Terraform and the platform database. These objects are encrypted at rest in
    the bucket.
  - Local-path volumes are skipped.
- A backup is kept for 14 days and then deleted. A deleted deployment
  therefore leaves the backups as the last 14 nightlies expire. A daily
  cleanup removes what the backup tool leaves behind afterwards, so nothing
  that names the deployment remains.
- An alert fires when no nightly backup has succeeded for 26 hours.
- Restores are an operator procedure for disaster recovery, documented in a
  runbook and rehearsed. Tenants still have no restore, as the Terms state.
- The Terms and the DPA say how long backup copies outlive a deletion.
  **BREAKING** for the Terms: §5.5 currently promises destruction after 1 day.

## Capabilities

### New Capabilities

- `volume-backups`: nightly, encrypted, off-cluster backups of the platform's
  replicated volumes and the Secrets they depend on; retention and purge of
  deleted deployments; staleness alerting; operator restore.

### Modified Capabilities

None.

## Impact

- **Terraform (`tf/deps`):** CSI snapshot support (snapshot controller, CRDs,
  one snapshot class and Ceph client for all pools); a new `velero` module
  (Velero, its node agent, credentials, schedule, policies); a `BackupTooOld`
  alert in the Prometheus module; four new secret variables.
- **Ceph:** one new cephx client with RBD access to every platform pool.
- **Bucket:** a dedicated S3 bucket. Each namespace with backed-up volumes gets
  its own encrypted repository there, named after the namespace.
- **Cluster load:** at most two data-mover pods at a time, each up to 1 GiB of
  memory, during the nightly run; a daily maintenance job per repository.
- **Legal:** Terms §5.5 and DPA §3.8 and Annex 1 retention wording.
- **Docs:** the ceph-csi README and the operator runbook.
