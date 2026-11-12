# Tasks

## 1. Snapshot plumbing

- [x] 1.1 Create `client.freepod-snapshots` with `profile rbd` on every platform pool, and add its key to `ceph_user_keys`; verified with `ceph auth get` showing the caps on both pools
- [x] 1.2 Install the snapshot controller and CRDs (`tf/deps/ceph-csi`), and the `ceph-rbd` VolumeSnapshotClass in its own release; verified the controller is running and the class lists with deletion policy `Delete`
- [x] 1.3 Document the snapshot client in the ceph-csi README and the runbook's pool section

## 2. Velero and encryption

- [x] 2.1 Add the `tf/deps/velero` module: namespace (privileged PSA), bucket credentials, repository password Secret created before Velero, Helm release (v1.18.4, AWS plugin v1.14.4, node agent on every node); verified the backup location is `Available`
- [x] 2.2 Enable SSE-C with a 32-byte key validated by Terraform; verified that none of a backup's metadata objects can be read without the key, and that they read and restore with it
- [x] 2.3 Back up and restore a dev namespace's claims into a scratch namespace; verified every file's checksum, owner, mode and size matches, apart from the fresh filesystem's `lost+found`

## 3. Schedule, limits and alerting

- [x] 3.1 Add the `velero-nightly` schedule: 00:30 UTC, TTL 336h, claims, volumes and Secrets only, Helm release records and the two system namespaces excluded; verified a run from the schedule completes 17/17 volumes
- [x] 3.2 Skip local-path volumes through a resource policy; verified a scheduled run reports 0 warnings
- [x] 3.3 Cap the data mover through the node-agent ConfigMap (one upload per node, one being prepared, 50m/384Mi request, 1Gi limit); verified at most 2 data-mover pods during a run, and the limits on the pods
- [x] 3.4 Set repository maintenance to daily, and switch the existing `BackupRepository` objects to it; verified on the server's arguments and on every repository's spec
- [x] 3.5 Add the `BackupTooOld` alert; verified it was pending before the first scheduled run and cleared after it
- [x] 3.6 Add a README to `tf/deps/velero`: a terse entry that links this change's spec, plus the two operator facts that aren't obvious from the code (the node agent reads its ConfigMap only at startup; run one manual backup after changing the backup location's settings); verified by review

## 4. Purge of deleted deployments

- [x] 4.1 Add the daily cleanup CronJob to `tf/deps/velero`. For each `BackupRepository` whose namespace no longer exists and that no DataUpload references, it deletes the `kopia/<namespace>/` prefix and then the object. Pick an image that already carries a Kubernetes and an S3 client, and give it least-privilege RBAC. Verify with `terraform plan` and a manual run, which reports nothing to remove on today's cluster
- [x] 4.2 Exercise the full purge on dev: create a scratch namespace with a Ceph claim, back it up with a short TTL, delete the namespace, and let the backup expire; then run the cleanup job. Verify that a run before expiry keeps the repository, and that afterwards no object under `kopia/<namespace>/` and no `BackupRepository` for it remain
- [x] 4.3 Measure the delay between a backup expiring and Velero deleting it with its DataUploads, on the task-4.2 namespace, and derive the deletion bound: TTL plus the garbage-collection interval plus one cleanup cycle, rounded up (16 days). Record the measurement in the runbook

## 5. Restore procedure

- [x] 5.1 Write the operator restore procedure (design D10) in the runbook, including how to read a backup's logs and results without the Velero CLI under SSE-C
- [x] 5.2 Rehearse it on a dev deployment with a database: stop, restore from the nightly into the same namespace, start. Verify the application starts against its restored database, and that the restored claims belong to the deployment's Helm release

## 6. Legal

- [x] 6.1 Amend Terms §5.5: a deleted deployment's live data is destroyed after 1 day, and its copies in operational backups expire within the bound from task 4.3. Verify that §5.3 and §5.4 (no restore on request) still read consistently
- [x] 6.2 Amend DPA §3.8 and the Annex 1 retention paragraph to match §5.5, and replace "routine backup cycles" with the stated bound; verified by review

## 7. Integration

- [x] 7.1 Run `terraform plan` for `tf/deps` from this branch and confirm "No changes" against the live cluster, so the applied state is exactly what merges
- [ ] 7.2 Open the PR; after merge, confirm the next 00:30 UTC run completes and `BackupTooOld` stays clear

## Workflow follow-up

- Archive this change after the PR merges and the first scheduled run has succeeded on master's configuration.
- Follow-up change: offsite copy on Hetzner Object Storage (second location, SSE-C, sub-processor entry in DPA Annex 3).
- Revisit D1 when Velero 1.19 is GA and velero-io/velero#10743 is resolved.
