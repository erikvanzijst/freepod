# Design

## Context

`deployment-storage-class` records a class on each new deployment. It takes the class from `user.storage_class`, an SQL-only account flag, and checks it against `CAELUS_STORAGE_CLASSES` (dev `["ceph-freepod-dev"]`, prod `["ceph-freepod"]`). Its D5 left the environment default to a later change, and this is that change.

- **Deployments**: those with volumes have all moved to their environment's Ceph class. The ones that still record no class have no PersistentVolumeClaim.
- **Platform**: the platform's own volumes are still on `local-path`. That covers the caelus databases, Garage, the registry, monitoring, Keycloak and mx, and most of them get that class only as the cluster default.

## Goals / Non-Goals

**Goals:**
- Every new deployment records the environment's class, whoever owns it.
- No live deployment is left that would put a newly added volume on the cluster default.

**Non-Goals:**
- Moving platform volumes off `local-path`. That is a separate change.
- Changing the cluster default StorageClass (D4).
- Any API, CLI or UI surface for the class. That stays as `deployment-storage-class` specifies.

## Decisions

### D1. One setting, `CAELUS_STORAGE_CLASS`, checked at startup

- **The setting.** `storage_class: str | None` sits next to `storage_classes`. When it is unset, new deployments record no class, as they do today without a flag. The local container and the test suite run that way.
- **The startup check.** A settings validator refuses a value that is not in `storage_classes`. A dev configured with the prod class then fails its rollout instead of every create.
- **The create-time check stays.** `_choose_storage_class` still refuses a class that is not on the list. Settings built with `model_copy` in tests skip validators, and the check costs nothing.
- **Rejected: use `storage_classes[0]`**, or the only entry. That hides the choice inside list order. The migration script already infers its `--to` that way, which works there only because a human reads its output.
- **Tofu:** `tf/app/locals.tf` already derives the list per workspace. The single class comes from the same local.

### D2. Drop `user.storage_class` instead of keeping it as an override

- **Why drop it.** An override would keep two selection paths, and nothing would use the second one. `local-path` is not on either allowlist, so an account could not be pinned to it anyway.
- **When to bring it back.** A future need for per-account placement, such as a second pool or a premium tier, would be a new design with its own surface. It would not revive an SQL-only flag.
- **One release, as every earlier column drop.** The model field and the drop migration ship together.
  - The API runs `RollingUpdate`, and its Alembic migration runs in the new pod's init container while the old pods still serve. For the seconds until the old pods stop, their `SELECT "user".storage_class` fails.
  - Rejected: two releases, with the field removed first and the column dropped later. `test_schema_drift` forbids a model and chain that disagree, and earlier drops (`health_timeout_sec`, `version_label`, `capabilities_json`) accepted the same window.

### D3. Record the class on claimless deployments with `migrate-storage.py`, not with Alembic

- **The script already does it.** `migrate` on a deployment that records no class and has no claims or StatefulSets records the target and touches nothing in the cluster ("no volumes to move"). It also holds the per-deployment lock and inspects the live namespace, for example a StatefulSet scaled to zero whose claims were deleted.
- **Rejected: an Alembic data migration.** It would write the class blind. It cannot see the cluster, so a deployment with a claim template but no live claim would get a class the renderer then adds to an immutable claim template.
- **Defaults.** `check_target` defaults `--to` to `CAELUS_STORAGE_CLASS` when it is set, and falls back to the single-entry rule otherwise.
- **The run.** It is a shell loop over `plan`'s claimless rows, run in `deploy/caelus-worker`. `plan` already counts those rows.
- **After the backfill**, a template upgrade that adds a volume to one of these deployments provisions it on Ceph. Before the backfill, that volume would land on `local-path`, as `deployment-storage-class` D1 warned.

### D4. The cluster default stays `local-path`

- **StorageClasses are cluster-wide.** One default would serve both dev and prod, so one environment's unclassed claims would land in the other's pool and quota.
- **The platform depends on the default.** Its Tofu-managed claims (caelus DB, static, tenant DB, registry, Garage, monitoring, Keycloak) name no class. Any one of them recreated under a Ceph default would come up empty on RBD. Such a move has to be planned per volume, with new PVC names (TF `storage_class_name` is ForceNew).
- **After D3, no tenant deployment depends on the default**, so flipping it buys tenants nothing.
- **When the platform volumes move**, the default can go too, and so can the `local-path` exception in the Velero resource policy.

## Risks / Trade-offs

- **[A deployment created before the release still records none]**. The release changes creates at once, so only deployments created before it can lack a class. → Run the backfill right after the release in each environment.
- **[Velero now backs up every new deployment, and the Ceph quotas fill faster]**. Each pool has a quota, and plan sizes are hard limits on RBD. → Watch the "Freepod: Ceph" pool panel. `CephHealthCheck` already fires on Ceph's `POOL_NEAR_FULL`, which Ceph raises as a pool nears its quota.
- **[Charts that work on `local-path` but not on a fresh RBD volume]**. Examples are a `lost+found` that trips initdb, or a root-owned 0755 mount. → Every catalog product passed the dev proof under `deployment-storage-class`. App Studio and `custom` already run on Ceph for the flagged accounts. A new product still gets its proof on dev before it is curated, and Ceph is now the only path that proof can exercise.
- **[Old pods fail user reads during the rollout]**. That lasts from the drop migration until the old API and worker pods stop, a few seconds. → Same as earlier drops. Roll out when no reconcile is in flight.
- **[Rolling back the image]** needs `alembic downgrade` first, which re-adds the column empty. The old image then records no class for every create, because no account is flagged. That is safe, only less placed.

## Migration Plan

1. **Dev.** Build an API and worker image, then apply with `CAELUS_STORAGE_CLASS=ceph-freepod-dev`. The init container drops `user.storage_class`. Create a deployment as an unflagged account and check that it records `ceph-freepod-dev` and that its claims are RBD and RWOP.
2. **Backfill dev.** Run `migrate-storage.py plan`, then `migrate` each claimless row, then run `plan` again and expect 0 claimless rows.
3. **Prod.** Repeat steps 1 and 2 with `ceph-freepod`.
4. **Rollback.** Downgrade one revision, then revert the image. The recorded classes stay, and the reconciler keeps rendering them, as `deployment-storage-class` D5 requires.
