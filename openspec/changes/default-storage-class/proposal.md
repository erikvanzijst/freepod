# Proposal

## Why

Every deployment with volumes now runs on Ceph, and nightly backups and restore drills cover it. A new deployment still lands on Ceph only when an operator has flagged its owner's account in SQL, though. Every other account, including every new signup, gets `local-path`: a volume on one node, with no quota and no backup. Now that there is nothing left to migrate, the opt-in has outlived its purpose.

## What Changes

- Each environment names the StorageClass its new deployments are created on: `ceph-freepod-dev` on dev, `ceph-freepod` on prod. Every new deployment records it, whoever owns it.
- **BREAKING (operator-only)**: the SQL-only account flag `user.storage_class` is removed. No API, CLI or UI ever exposed it.
- The environment's class must be one of the classes it allows. An environment that names none keeps today's behavior: deployments record no class, and their volumes are rendered as their charts render them. Local development and the test suite work this way.
- The live deployments that still record no class have no volumes. `migrate-storage.py migrate` records the environment's class on them. After that, a template upgrade that adds a volume to any of them provisions it on Ceph, not on the cluster default.
- The cluster default StorageClass stays `local-path`. Dev and prod share it, and platform volumes outside tenant deployments still rely on it.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-storage-class`: the class comes from the environment instead of the owner's account. The three selection requirements are replaced by environment-based ones, and the account-flag requirement is removed.

## Impact

- `api/app/config.py`: new `storage_class` setting (`CAELUS_STORAGE_CLASS`), checked against `storage_classes` at startup.
- `api/app/services/deployments.py`: `_choose_storage_class` reads the environment, not the owner.
- `api/app/models/core.py` + an Alembic migration: drop `user.storage_class`.
- `api/bin/migrate-storage.py`: `--to` defaults to the environment's class.
- `tf/app`: `CAELUS_STORAGE_CLASS` per workspace, next to `CAELUS_STORAGE_CLASSES`.
- Tests in `api/tests/test_deployments.py`, `test_config.py` and `test_migrate_storage_script.py`.
- Rollout: one API and worker image per environment, then a migrate run over the claimless deployments.
