# Tasks

## 1. Maintenance power reason

- [x] 1.1 `POWER_REASON_MAINTENANCE`, the read model's reason type, and a migration widening `ck_deployment_power_reason`
- [x] 1.2 `begin_maintenance` / `end_maintenance` in `app/services/power.py`; start refuses with `under_maintenance`
- [x] 1.3 `update_deployment` refuses with `under_maintenance`, in its pre-check and in the guarded `UPDATE`
- [x] 1.4 Endpoint docs name the new code
- [x] 1.5 Service and REST tests

## 2. Clients

- [x] 2.1 Dashboard: Maintenance label, no Edit, refusal text; tests
- [x] 2.2 `freepod` 0.25.1: `start` and `deploy` explain `under_maintenance`; tests

## 3. Script

- [x] 3.1 `api/bin/migrate-storage.py`: `plan`, `migrate` (with `--dry-run`), `rollback`, `cleanup`
- [x] 3.2 Fake-cluster tests for claim discovery, refusals and switch order

## 4. Dev proof

- [ ] 4.1 Release the API and worker to dev
- [ ] 4.2 Migrate one deployment of each shape: Helm claims only; a StatefulSet database; several claims; one on each node; one already stopped
- [ ] 4.3 Kill a run mid-copy and mid-switch; rerun finishes it
- [ ] 4.4 Roll one back, then migrate it again
- [ ] 4.5 `cleanup` deletes the released volumes on both classes

## 5. Production

- [ ] 5.1 A backup of the new class exists and has been restore-tested
- [ ] 5.2 Grow any claim whose data is over 80% of its size
- [ ] 5.3 Migrate one deployment at a time

## 6. Archive

- [ ] 6.1 AGENTS.md: point the power and storage class entries at `deployment-storage-migration`
