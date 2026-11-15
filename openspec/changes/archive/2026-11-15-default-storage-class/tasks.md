# Tasks

## 1. Environment class

- [x] 1.1 `CaelusSettings.storage_class` (`CAELUS_STORAGE_CLASS`, unset = none), with a validator refusing a value outside `storage_classes`. Verify with `test_config.py` cases for unset, allowed, and not allowed (raises, naming the class).
- [x] 1.2 `_choose_storage_class` reads the environment's class and ignores the owner. Remove `UserORM.storage_class`. Verify with `test_deployments.py`: unflagged owner on an environment naming `ceph-freepod` records it; an admin creating for another account records it; an unset environment records none; a class off the list is refused with nothing stored. Rewrite the existing flag-based tests, and keep the "no read model reports a class" and "a class field is ignored" tests passing.
- [x] 1.3 `migrate-storage.py`: `check_target` defaults `--to` to `CAELUS_STORAGE_CLASS`, and falls back to the single-entry rule when unset. Verify with `test_migrate_storage_script.py`.
- [x] 1.4 Terraform: `CAELUS_STORAGE_CLASS` in `tf/app/caelus/configmap.tf` from a per-workspace local in `tf/app/locals.tf`. Verify with `TF_WORKSPACE=default` and `TF_WORKSPACE=prod`: `terraform plan` shows only the configmap key added.
- [x] 1.5 Alembic migration dropping `user.storage_class`; the downgrade re-adds it as nullable. Verify with `test_schema_drift.py` and an `upgrade head` / `downgrade -1` / `upgrade head` round trip on a scratch database.
- [x] 1.6 Point the storage-class entry in AGENTS.md at this change's rationale. Verify that the full `api/` suite passes (`-n 8`).

## 2. Dev rollout

- [x] 2.1 Release the API and worker image to dev, and apply tf/app on the `default` workspace. Verify that `user.storage_class` is gone, and that a deployment created by an unflagged dev account records `ceph-freepod-dev`, and its claims are `ceph-freepod-dev` / `ReadWriteOncePod`.
- [x] 2.2 Backfill: run `migrate-storage.py migrate` on each claimless row from `plan`, in `deploy/caelus-worker`. Verify that `plan` reports no claimless deployments and that they reconcile unchanged.

## 3. Prod rollout

- [x] 3.1 Release to prod with `ceph-freepod`. Verify with one fresh deployment by an unflagged account, as in 2.1.
- [x] 3.2 Backfill the claimless prod deployments as in 2.2. Verify that `plan` reports none and that no reconcile failed afterwards.

## Workflow follow-up

- Archive the change and sync the delta into `openspec/specs/deployment-storage-class`.
- Repoint the AGENTS.md rationale link at the archived design.
