# Design

## Context

- **Storage today.** Tenant volumes come from the cluster default StorageClass,
  `local-path`.
  - No catalog chart names a class. Each has its own `storageClassName` value
    (16 charts, 33 templates, at different value paths), and every one renders
    it only when it's non-empty.
  - So every live PersistentVolumeClaim was defaulted to `local-path` at
    creation.
  - Every live StatefulSet volume claim template names no class at all.
- **Ceph classes.** `tf/deps/ceph-csi` provides `ceph-freepod` and
  `ceph-freepod-dev`: ext4 on krbd, `discard`, online expansion, reclaim
  `Delete`. The RBD driver supports `ReadWriteOncePod`.
- **Immutable fields.** Kubernetes rejects changes to a claim's
  `storageClassName` and `accessModes`, and to a StatefulSet's
  `volumeClaimTemplates`.
- **Helm 4 server-side apply.** Releases are applied this way. A field the
  release asserted and then stops asserting is removed, and for these fields
  that removal is an illegal update.
- **The post-renderer** (`app/post_render.py`) is the platform's single rewrite
  pass over every tenant release. It already injects the egress gate and
  renders stopped deployments.
- **Existing chart tests.** `test_chart_rollout_strategy.py` already holds every
  Deployment that mounts a claim to `Recreate`, with helloworld as the one
  documented exception. No catalog chart mounts a claim from two workloads or
  renders a CronJob.
- **Postgres on a fresh volume.** A new ext4 volume's root holds `lost+found`.
  `initdb` refuses a non-empty data directory: verified against `postgres:17`,
  "It contains a lost+found directory". MySQL 26.7 and MariaDB 12.3 initialize
  next to it.
  - Three charts use the volume root as `PGDATA`: immich and immich-sso
    (`/var/lib/postgresql/data`, Immich's Postgres 14 image) and openproject
    (`postgres:17`, the same path).
  - The other bundled databases already use a subdirectory, or the versioned
    layout under `/var/lib/postgresql`.

## Goals / Non-Goals

**Goals:**
- New deployments can land on Ceph, per environment and per account, with no
  chart changes beyond the three Postgres fixes.
- Existing deployments render byte-for-byte as before.
- A volume on Ceph can never have two writers.

**Non-Goals:**
- Changing an existing deployment's class. Volume migration is its own change,
  and that change will be the only writer of `deployment.storage_class` after
  creation.
- Showing the class in the API, CLI or UI.
- Changing the cluster default StorageClass. It stays `local-path` while any
  deployment records no class (D1).

## Decisions

### D1. The deployment records its class; null means "don't touch"

`deployment.storage_class` is a nullable string, set in `create_deployment` and
never updated by any service in this change.

- **Why null and not a backfilled `local-path`.** Rendering `local-path`
  explicitly would add a class to every live StatefulSet claim template. That is
  a forbidden StatefulSet update, so every existing deployment with a claim
  template would fail its next upgrade.
- **Null keeps the old behavior.** The post-renderer step is skipped, and the
  release asserts nothing about class or access mode, exactly as today.
- **The cost.** A null deployment whose chart later adds a claim gets the
  cluster default. So `local-path` must remain the default until no null
  deployment holds volumes.
- **Rejected: derive the class at render time** from the account or the
  environment. Changing either would then change the render of deployments
  whose volumes already exist, and their upgrades would fail. The class is a
  fact about objects already in the cluster, so it lives on the row.

### D2. Applied by the post-renderer, not by the charts

A new step, `--storage-class=<name>`, is passed only when the deployment records
a class. It handles two kinds of objects:
- every `PersistentVolumeClaim` in the release;
- every `volumeClaimTemplates[]` entry of every StatefulSet.

For each, it sets `spec.storageClassName` to the class and `spec.accessModes` to
`[ReadWriteOncePod]`. It overrides whatever the chart rendered.

- **Rejected: a `caelus.storage.className` system value read by each chart.**
  That means 33 templates, each changed, versioned and kept honest by a new
  contract test. One missed claim would silently land on the default class.
  - The post-renderer covers every chart without its cooperation. That includes
    charts not yet written and the admin-authored SSO variants.
  - It keeps the rule in one place, where the immutability argument (D1) is
    enforced.
- **Charts don't need to know their class.** The one case where one did (the
  Postgres data directory, D6) has a fix that is correct on every class.

### D3. `ReadWriteOncePod` on every claim of a class-bearing deployment

Access modes are immutable too. A new Ceph volume created as `ReadWriteOnce`
would need a second migration to become single-pod later.

- **The problem RWOP fixes.** RWO allows any number of pods on one node to mount
  the volume. That is the two-writers-on-one-database problem that `Recreate`
  only half fixes: an evicted or deleted pod's replacement can still start
  before it has terminated.
- **With RWOP**, the scheduler holds the replacement until the volume is
  released.
- **Why every claim.** The catalog already meets the precondition (one pod per
  claim). A per-volume opt-in would only add a decision every chart author
  could get wrong.
- **Rejected: RWOP only for database volumes.** The SFTP sidecar and the app
  share their volume inside one pod, which RWOP allows. No catalog volume needs
  a second pod.

### D4. Refuse a violating release; don't repair it

When the release violates the single-pod precondition, the post-renderer exits
non-zero with a message naming the claim. Helm then fails before applying
anything, and the reconcile fails the way any render error does. The violations
are:
- a claim in the release is mounted by two pod templates;
- a claim is mounted by a Deployment with more than one replica, or with a
  strategy other than `Recreate`;
- a claim is mounted by a StatefulSet with more than one replica (a claim
  mounted by name, not through a claim template);
- a claim requests an access mode other than `ReadWriteOnce`.

Claims the release doesn't render (pre-existing PVCs) aren't checked or
rewritten.

- **Rejected: rewriting the strategy to `Recreate`**, or quietly keeping RWO for
  a shared claim. Either would make the platform's behavior depend on chart
  shapes nobody reviewed.
- **Why refusing is safe.** It only applies to class-bearing deployments. A
  chart that violates the contract fails on dev, on its first Ceph deployment,
  never on an existing tenant.
- **helloworld**, the one chart allowed to roll its claim, would be refused on
  Ceph. It isn't a catalog product.

### D5. Selection: the account column, checked against an allowlist

- **The account.** `user.storage_class` is nullable and has no API, CLI or UI
  surface. Operators set it with SQL, which also keeps the API/CLI parity rule
  untouched.
- **No environment default.** Dev and prod select the same way, so the prod
  canary runs exactly the path dev proved. "Every new deployment on Ceph" is a
  later change, after backups exist and existing deployments have moved. That
  change adds the default; this one would only carry it unused.
- **The allowlist.** `CAELUS_STORAGE_CLASSES` is a JSON list, the existing
  `list[str]` convention. Dev allows `ceph-freepod-dev`; prod allows
  `ceph-freepod`.
  - StorageClasses are cluster-scoped, so without the list, a dev account
    flagged with `ceph-freepod` would provision into prod's pool. A typo would
    leave PVCs Pending forever.
- **At create**, the owner's class must be on the list, or the create raises
  before anything is flushed.
- **The list governs selection only.** The reconciler renders whatever the row
  records, even after the class is removed from the list, because the volumes
  exist.
- **Rejected:** a list of account IDs in configuration (DB state belongs in the
  DB); a general feature-flag table (one flag doesn't justify it); checking the
  class against the cluster at create time (the API has no cluster-scoped read
  on StorageClasses, and a list is testable).
- **When Ceph becomes the default** (a later change), the account column
  becomes redundant and can be dropped.

### D6. The Postgres fix: remove an empty `lost+found` before Postgres starts

The immich, immich-sso and openproject Postgres pods get an init container. It
uses the same image, runs as the image's default user (root, as the main
container does before it drops privileges), and runs
`rmdir <PGDATA>/lost+found 2>/dev/null || true`.

| Volume | What happens |
|---|---|
| Fresh Ceph volume | `lost+found` is removed and `initdb` runs. |
| Existing volume with data at its root | The `rmdir` finds nothing and fails quietly; Postgres starts on its data. |
| Volume where a filesystem check left files in `lost+found` | The `rmdir` fails quietly; a running server ignores the directory. |

Removing `lost+found` is safe on ext4. The kernel never uses it: orphan
handling at mount goes through the superblock's orphan list. Only `e2fsck` uses
it, and `e2fsck` recreates it when it's missing. Tested with e2fsprogs 1.47.2
on an image whose `lost+found` had been removed:

| Check | Result |
|---|---|
| Read-only check (`-n -f`) | Exit 0, no complaint. |
| Preen on a clean filesystem (`-p`) | Skipped as clean; nothing recreated. |
| Forced preen (`-f -p`) | "/lost+found not found. CREATED."; exit 1 (errors corrected), which mount tooling accepts. |
| An unattached inode, under `-f -p` | Stops with "UNEXPECTED INCONSISTENCY", exactly as with `lost+found` present. |
| An unattached inode, under `-f -y` | Recreates the directory and reconnects the inode there, exactly as with it present. |

So the directory comes back only after a full check. If that happens, the next
pod start removes it again if it's empty.

- **Rejected: move `PGDATA` to a subdirectory.** Existing deployments' data is
  at the volume root. The first upgrade would initialize an empty cluster beside
  it and serve that. A data move would have to ride along with the chart
  upgrade.
- **Rejected: Postgres 18's versioned layout.** A major-version upgrade is its
  own change.
- **Upstream's warning against mount points as `PGDATA`** guards against a
  failed mount silently initializing on the root filesystem. A pod whose volume
  fails to mount never starts, so that risk doesn't apply here.

### D7. Nodes unmount kubelet volumes before their network stops

kubelet mounts ext4-on-RBD filesystems without `_netdev`, so systemd treats them
as local disks.

- **The failure.** In an orderly shutdown, systemd stops the network first and
  unmounts local filesystems last. Unmounting then has to flush to a block
  device that is now unreachable. krbd waits for the OSDs indefinitely by
  default, so the shutdown hangs.
- **A crash is different.** There is no unmount, so nothing hangs. On the next
  map, the volume's ext4 journal replays. Ceph expires the dead client's watch
  and breaks its exclusive lock, because the cephx `profile rbd` allows the
  blocklist.
- **The fix.** A unit on each node, ordered `After=network-online.target`. It
  is therefore stopped before the network. Its `ExecStop` runs k3s's
  `k3s-killall.sh`, which stops containers and unmounts everything under
  `/var/lib/kubelet/pods` and `/var/lib/kubelet/plugins` (CSI staging mounts
  included) while the OSDs are still reachable.
- **Documented, not managed.** The unit goes in the ceph-csi module's README,
  next to the kernel requirement, because node OS configuration isn't in
  Terraform.
- **Rejected:**
  - Kubernetes graceful node shutdown: kubelet would terminate pods, but it
    doesn't guarantee volume teardown within the grace period, and it changes
    how every pod behaves across a reboot.
  - Relying on operators to stop pods before rebooting: unattended shutdowns,
    such as a hypervisor shutting its guests down, don't read runbooks.

## Risks / Trade-offs

- **Sizes become real.** local-path never enforced a claim's size; RBD does. So
  a chart default (a database's 5–20Gi, App Studio's 10Gi) is now a hard limit.
  → RBD volumes report usage through kubelet volume stats, so this change adds
  a volume-filling alert. A volume grows online when the plan's or the chart's
  size value grows. A size cut in the chart is refused by Kubernetes, as
  before.
- **One pool per environment, shared and thin-provisioned.** A pool at quota
  blocks writes to every volume in it. → Pool quota alerts exist (80% / 95%).
  In prod, only flagged accounts provision on Ceph at first.
- **Commit latency.** Every write crosses the LAN to three replicas, so a
  database commit costs a few milliseconds where local disk costs under one.
  → Fine for mostly idle tenant apps. Re-measure once the dedicated cluster
  network is in.
- **No volume backup yet.** Prod volumes on Ceph aren't covered by the existing
  host-level backups. → Only operator-flagged accounts get Ceph until the
  volume backup change lands.
- **gVisor and RBD together are untested.** → App Studio, which runs under
  gVisor and mounts a claim, is part of the dev proof.
- **A node failure doesn't move single-node volumes.** Kubernetes won't detach
  an RWO/RWOP volume from a node that's down. → Tenant pods are pinned to their
  node pool today, so they wait for the node either way. The out-of-service
  taint is the documented way to release the volume when a node is gone for
  good.
- **Code rollback is one-way once a class is recorded.** An API without the
  storage step would stop asserting the class and access mode. Server-side
  apply would then try to remove them, and Kubernetes refuses, so those
  deployments' reconciles fail. → Roll forward. Clearing the settings stops new
  Ceph deployments without touching existing ones.

## Migration Plan

1. **Release the API with the migration and an empty allowlist.** No account
   is flagged and every deployment records null, so nothing renders
   differently anywhere.
2. **Publish the three chart patch releases.**
   - immich and openproject: new curated templates through the catalog.
   - immich-sso: a new admin-authored template.
   - Move existing deployments to them; the fix is backward compatible.
3. **Dev.** Allow `ceph-freepod-dev` and flag the operator's dev account with
   it in SQL. From that account, create one deployment of every catalog
   product, plus immich-sso. For each:
   - it starts;
   - its claims are on `ceph-freepod-dev` with RWOP;
   - stop, start, a template move and a deletion all behave (the RBD image is
     removed);
   - App Studio under gVisor reads and writes its project volume.
4. **Install the node unit on both nodes and run a reboot drill** in a
   maintenance window, since the nodes are shared by both environments. Run it
   once with a mounted RBD volume and without the unit, to confirm the hang.
   Then run it with the unit, to confirm a clean shutdown.
5. **Prod.** Allow `ceph-freepod`, then flag the operator's account in SQL,
   exactly as on dev.

**Rollback:** clear the account flags. New deployments record null again, and
deployments already on Ceph keep rendering their class (see the last risk for
code rollback).
