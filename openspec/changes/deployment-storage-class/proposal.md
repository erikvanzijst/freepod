# Proposal

## Why

Every tenant volume is on `local-path`. That means:
- it lives on one node's disk;
- its size is never enforced;
- it can't be grown;
- a pod replacement can briefly put two writers on one database.

The cluster now has a replicated Ceph RBD pool per environment (`ceph-freepod`,
`ceph-freepod-dev`), but nothing provisions onto it. New deployments need a way
onto Ceph that never disturbs existing ones. A PVC's class and access modes, and
a StatefulSet's claim templates, can't change once created. So the class has to
be a fact the platform records per deployment and applies itself, not a setting
read at render time.

## What Changes

- Each deployment records the StorageClass its volumes are provisioned on, as
  the nullable `deployment.storage_class`.
  - Null means the platform leaves the chart's volumes exactly as it renders
    them, which is what every existing deployment gets.
  - The value is chosen once, when the deployment is created, and is never
    changed through the API, the CLI or the UI.
- The class is chosen from the owning account's `user.storage_class`, and is
  none when the account names none.
  - The account column is a rollout flag that only an operator sets, in the
    database.
  - Dev and prod choose the same way; neither has a default class.
  - The account's class must be on the environment's list of allowed classes,
    so a dev deployment can never land in prod's pool.
- The platform's Helm post-renderer applies a deployment's class to every
  PersistentVolumeClaim and StatefulSet claim template in the release, in every
  render mode, and requests `ReadWriteOncePod` for each of them.
  - It refuses to render a release where a claim could be mounted by more than
  one pod at a time.
- Charts start on a freshly formatted volume, whose root holds `lost+found` and
  is writable by root only (local-path's directories are world-writable).
  - The immich, immich-sso and openproject Postgres, and Docmost's Redis, get
    an empty `lost+found` removed first: `initdb` refuses it, and Redis's
    entrypoint then skips fixing its directory's ownership.
  - Mattermost, whose server runs as a user other than root, gets an `fsGroup`.
- Nodes release their RBD volumes before their network stops when they shut
  down cleanly. This is documented beside the ceph-csi module, because node OS
  configuration isn't managed by Terraform.
- Rollout: dev first. The operator's dev account is flagged with
  `ceph-freepod-dev`, and every catalog product is shown to run on Ceph. Then
  prod, where the operator's account is flagged with `ceph-freepod`.

Out of scope, each a later change:
- moving existing deployments' volumes onto Ceph;
- the tenant registry, Garage, the tenant database cluster, the platform
  database and Keycloak;
- volume backups.

## Capabilities

### New Capabilities

- `deployment-storage-class`: how a deployment's StorageClass is chosen,
  recorded and kept, and how the platform applies it to the deployment's
  volumes at render time.
- `storage-chart-contract`: what a product chart must do for its volumes to run
  on any of the platform's StorageClasses: claims mounted by one pod, Deployments
  that mount a claim replaced with `Recreate`, data directories that start on a
  freshly formatted filesystem, and writers that are not root getting access
  through `fsGroup`.

### Modified Capabilities

- `deployment-power-reconciliation`: a stopped render keeps the deployment's
  storage class on its volumes, like the platform's other post-render steps.

## Impact

- **Database:** one migration adds nullable `storage_class` columns to `user`
  and `deployment`. There is no backfill.
- **API:**
  - `app/config.py`: the allowed classes.
  - `app/services/deployments.py`: selection at create.
  - `app/post_render.py`: the storage step.
  - `app/provisioner.py` and `app/services/reconcile.py`: pass the class
    through.
  - No API, CLI or UI field changes.
- **Terraform:** `tf/app/caelus` sets the two settings per workspace.
- **Charts:** immich, immich-sso, openproject, mattermost and docmost get patch
  releases. The curated products get new catalog templates. The admin-authored
  immich-sso product gets a new template by hand.
- **Operations:**
  - A node unit that unmounts kubelet volumes while the network is still up,
    with a reboot drill on both nodes.
  - Prod volumes on Ceph are not covered by the existing host-level backups.
    Only operator-flagged accounts get Ceph until a volume backup exists.
