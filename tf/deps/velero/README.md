# velero

Nightly Velero backups of the Ceph volumes and the Secrets they depend on, to
an S3 bucket, plus a daily job that removes the repositories of deleted
namespaces: [volume-backups](../../../openspec/specs/volume-backups/spec.md).

Two things the code doesn't show:

- **The node agent reads `velero-node-agent` only at startup.** After changing
  it, run `kubectl -n velero rollout restart daemonset/node-agent`.
- **After changing the backup location's settings, run one backup by hand.**
  Velero re-establishes its repositories, and the first run afterwards can fail
  its uploads while it does:
  `velero backup create --from-schedule velero-nightly`.
