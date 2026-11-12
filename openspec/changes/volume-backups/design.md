# Design

## Context

- Tenant and platform volumes are on `local-path` or on the Ceph RBD
  StorageClasses (`ceph-freepod`, `ceph-freepod-dev`); see the
  `deployment-storage-class` spec. Local-path data lives inside the nodes, and
  the nodes are backed up as whole machines. Ceph data is in neither.
- k3s ships no CSI snapshot CRDs or snapshot controller. The ceph-csi
  provisioner already runs the `csi-snapshotter` sidecar.
- Each pool has its own cephx client, which can reach only that pool.
- The backup target is a self-hosted S3 store (Garage) in its own bucket. It
  needs path-style addressing; it accepts the AWS SDK's default request
  checksums and SSE-C.
- Dev and prod share one cluster. Tenant namespaces carry
  `caelus.dev/environment`, and every namespace name is derived from the owner's
  handle.
- Most of this design is already applied, from the branch that carries this
  change; see Migration Plan.

## Goals / Non-Goals

**Goals:**

- A disaster-recovery copy of every Ceph volume, plus what the platform cannot
  regenerate, outside the Ceph cluster.
- Nothing about a deleted deployment survives in the backup system past a
  bound we can state in the Terms.

**Non-Goals:**

- An offsite copy (Hetzner Object Storage). It needs its own location,
  credentials, sub-processor entry and a choice between a second schedule and a
  bucket mirror; a follow-up change.
- Restores for tenants, through any channel (Terms §5.4).
- Application-consistent snapshots. Snapshots are crash-consistent: a restored
  database recovers as after a power cut.
- Local-path data. The node backups cover it until the deployment migrates.
- Logical dumps of the platform database.

## Decisions

### D1. Velero 1.18 with the file-level data mover

Velero snapshots each claim through CSI, clones the snapshot into a temporary
claim, and uploads its files with Kopia. Kopia's file cache skips unchanged
files, so nightly runs read and send only what changed.

- **Velero 1.19's block data mover:** rejected for now. On Ceph RBD it reads
  every allocated block on every run (velero-io/velero#10743), and 1.19 is a
  release candidate. Revisit both at 1.19 GA.
- **Rolling snapshots inside Ceph:** rejected. They don't survive the loss of
  the pool, which is what this change is for.
- **Borg or rsync from mounted snapshots:** rejected. Velero already does the
  snapshot, clone, mount, upload and expiry cycle that we would otherwise write
  and maintain ourselves.

Velero runs image v1.18.4 on chart 12.2.5 (whose app version is 1.18.2), with
the AWS object-store plugin v1.14.4.

### D2. Snapshot plumbing: one class, one client for every pool

- **Snapshot controller and CRDs:** the snapshot controller (v8.7.0) and its
  CRDs come from the Piraeus `snapshot-controller` chart. The CRDs are kept if
  the chart is uninstalled, so uninstalling cannot delete every snapshot.
- **One VolumeSnapshotClass, `ceph-rbd`,** labeled for Velero. Velero picks a
  single class per CSI driver, and a class names one snapshotter secret. So the
  class uses a dedicated client, `client.freepod-snapshots`, with `profile rbd`
  on every platform pool. Snapshots stay in their volume's pool.
  - **Alternative:** a class per pool, chosen through an annotation on each
    claim. Rejected: the platform would have to write backup configuration into
    every chart render.
- **The class is in its own Helm release.** In the same release as the CRDs,
  Helm fails on first install, because it resolves every kind before it creates
  the CRDs.

### D3. Scope: claims, volumes and Secrets only

One schedule covers every namespace except `kube-system` and `velero`. It
includes only `persistentvolumeclaims`, `persistentvolumes` and `secrets`, and
excludes `owner=helm` objects, which are Helm's release records.

- **Workloads and routing are left out.** Terraform rebuilds the platform, and
  the reconciler rebuilds every deployment from the platform database. A
  restored Deployment or Ingress would only compete with Helm.
- **Claims are needed by the mechanism.** Velero backs up a volume's data when
  it backs up the claim, and recreates the claim when it restores the data.
- **Secrets are needed for the data to work.** Eleven product charts generate
  passwords and signing keys at install time and keep them only in Secrets.
  Restored data without its Secret is unusable: the application can't log in to
  its own database, and anything signed or encrypted with the old key is lost.
- **Local-path volumes are skipped** by a Velero resource policy matching their
  StorageClass. Without it, every run carries two warnings per local-path
  volume, which would hide real warnings.
- **One schedule for both environments.** Velero can't select namespaces by
  label. Dev's volumes are small, and dev backups give us a safe place to
  rehearse restores.

### D4. Two layers of encryption, two keys

- **Volume data:** Kopia encrypts it (AES256-GCM) inside the cluster, keyed from
  the repository password.
  - Terraform creates `velero-repo-credentials` before Velero first starts.
    Velero would otherwise create it with a built-in, publicly known password.
- **Other backup objects:** the resource tarball, logs and results are written
  by the AWS plugin rather than by Kopia, so Kopia's encryption never covers
  them.
  - They are stored with SSE-C (`customerKeyEncryptionSecret`), using a 32-byte
    key the store discards after each request.
  - Kopia's own S3 client is never given the SSE-C settings, so volume data is
    not encrypted twice.
- **Both keys live in `secrets.auto.tfvars` and in the operator's password
  manager.** Without both, the backups are unreadable.
- **Consequence:** the Velero CLI's `backup describe --details`, `backup logs`
  and `backup download` fail. They fetch through pre-signed URLs, and the store
  rejects those without the SSE-C headers. Operators read the server log
  (`kubectl logs`) or fetch objects with the key instead (runbook).

### D5. Schedule and retention

- **When:** daily at 00:30 UTC. That keeps clear of the upgrader (01:00–03:00
  UTC), whose Helm upgrades should not be snapshotted halfway, of the 03:00
  image and registry cleanup, and of the 04:00 node backup.
- **How long:** each backup has a TTL of 336h (14 days).
- **No hooks.** Snapshots are crash-consistent; see Non-Goals.

### D6. Concurrency and memory

By default the data mover creates one pod and one snapshot clone per claim, all
at the start of the run. The node-agent ConfigMap limits that:

- **Concurrency:** `loadConcurrency.globalConfig = 1` and
  `prepareQueueLength = 1`, so at most one upload per node plus one volume
  being prepared.
- **Pod resources:** a request of 50m CPU and 384Mi memory, and a limit of 1Gi.
  - **Measured:** about 390 MiB while uploading 1.2–1.5 GB volumes, and about
    18 MiB while waiting.
  - **Format:** Velero rejects the block unless all six fields are set; `"0"`
    means unset.
- **The node agent reads this ConfigMap only at startup.** A change needs a
  restart of the DaemonSet.

### D7. Daily repository maintenance

- **One repository per namespace.** Velero keeps a Kopia repository per
  namespace and runs a maintenance Job for each, hourly by default. We set
  `defaultRepoMaintainFrequency` to 24h.
- **The default applies only when a repository is created.** Existing
  `BackupRepository` objects keep the frequency they were created with.
- **Maintenance frees the data of expired snapshots.** The daily cycle sets how
  long that data outlives its last backup; measured in tasks.

### D8. Purge of deleted deployments

- **What already works:**
  - A deleted deployment's namespace no longer exists, so later backups skip
    it.
  - Its last 14 nightlies expire one by one; with each, Velero deletes the
    backup's objects, its Secrets and its Kopia snapshots.
  - Maintenance then removes the data no snapshot references.
- **What Velero never deletes:** the namespace's `BackupRepository` object, and
  the repository's remaining files under `kopia/<namespace>/` (format, indexes,
  manifests).
  - The prefix contains the namespace name, and so the owner's handle.
  - The object keeps a daily maintenance Job running.
- **A daily cleanup CronJob in the `velero` namespace removes both** for a
  namespace that:
  1. no longer exists, and
  2. no DataUpload references any more.
- **Why rule 2 is enough:** Velero deletes a backup's DataUploads together with
  the backup, so rule 2 holds exactly when the last backup that included the
  namespace has expired. The job needs bucket credentials but no SSE-C key,
  since none of the repository's objects use SSE-C.
- **Alternatives rejected:**
  - **A step in the platform's deletion flow:** it would tie the reconciler to
    the backup system, and it would still have to wait 14 days.
  - **A schedule per namespace:** with as many schedules as deployments, the
    expiry is no easier to follow.
- **The bound in the Terms** is the TTL, plus the measured maintenance delay,
  plus one cleanup cycle, rounded up.

### D9. Staleness alert

`BackupTooOld` is critical, with a `for` window of 30m. It fires when
`velero_backup_last_successful_timestamp{schedule="velero-nightly"}` is more
than 26h old, or absent.

- **A partly failed backup doesn't count:** it does not update that timestamp,
  so it surfaces as staleness.
- **The absent branch** also catches a Velero that is down, or has never
  completed a run.

### D10. Operator restore

The procedure, for the runbook:

1. Stop the deployment through the platform. Its pods release their
   `ReadWriteOncePod` claims, and the reconciler leaves it alone.
2. Delete its claims.
3. Restore from the chosen backup, limited to that namespace and to claims,
   volumes and Secrets, with `--existing-resource-policy=update`. That
   overwrites the Secrets the reconciler regenerated.
4. Start the deployment.

The restored claims keep their Helm labels and annotations, so Helm adopts
them. The rehearsal checks every step against a real dev deployment.

**After changing the backup location's settings,** run one backup by hand.
Velero re-establishes its repositories after such a change, and the first run
afterwards can fail its uploads while it does.

## Risks / Trade-offs

- **[The bucket shares a site with the cluster]** → The offsite copy follows in
  its own change. Until then, this covers loss of the Ceph cluster, not of the
  site.
- **[Losing the repository password or the SSE-C key makes every backup
  unreadable]** → Both are kept outside the cluster. The rehearsal restores
  using only what is in `secrets.auto.tfvars`.
- **[Crash-consistent snapshots across volumes of one app]** → For example,
  Immich's database and photo library are snapshotted seconds apart. A restore
  behaves like recovery from a power cut. Accepted.
- **[Run time grows with the number of volumes]** → Volumes are processed one
  at a time, at roughly 20 s fixed cost each: 17 volumes take 6.5 min. At a few
  hundred, revisit the per-node concurrency.
- **[Operators lose the Velero CLI's detail views under SSE-C]** → Runbook
  commands read the server log or fetch objects with the key.
- **[A restore races the reconciler]** → The deployment stays stopped until the
  restore completes.

## Migration Plan

- **Already live:** the snapshot plumbing, the Velero install, SSE-C, the
  schedule, the concurrency cap and the alert are applied from this branch.
  Until the branch merges, applying `tf/deps` from master would remove them.
  Merge before anyone else applies `tf/deps`.
- **One-time steps done by hand:**
  - created `client.freepod-snapshots` and stored its key;
  - deleted the test backups that predate SSE-C;
  - set existing `BackupRepository` objects to daily maintenance.
- **Rollback:** uninstall the Velero release. The snapshot CRDs, and the backups
  in the bucket, remain.
