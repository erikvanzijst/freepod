# Proposal

## Why

Deployments created before `deployment-storage-class` record no class, so their
volumes stay on `local-path`: one node's disk, sizes not enforced, no growth.
Moving them means copying each volume while nothing writes to it, and swapping
it under a claim name the release fixes. A claim's class and access modes, and
a StatefulSet's claim templates, can't be changed in place.

The move runs once per deployment and then never again, so it belongs in an
operator script rather than in the API or `caelus`. But the platform has to
keep the deployment still while the script works: today the owner can start a
stopped deployment, or roll out a release, at any moment.

## What Changes

- A third power reason, `maintenance`.
  - An operator stops a ready deployment for maintenance, whatever its power,
    and later returns it to the power it last had applied before.
  - While it lasts, start and update are refused with `409` and code
    `under_maintenance`. Stop changes nothing, and delete is still accepted.
  - The dashboard shows **Maintenance** and offers no Start, Stop or Edit. The
    `freepod` client explains the refusal on `start` and `deploy`.
- `api/bin/migrate-storage.py`, run in the reconcile worker's pod:
  - `plan` lists the deployments still on `local-path`.
  - `migrate` holds one deployment for maintenance, copies and verifies each
    volume onto the environment's class, records the class, has the release
    claim the copies under their old names, and returns the deployment to its
    power.
  - `rollback` puts a migrated deployment back on its kept `local-path`
    volumes.
  - `cleanup` deletes the volumes that `migrate` or `rollback` released, once
    they are old enough.
- The script is the only writer of `deployment.storage_class` after creation,
  as `deployment-storage-class` anticipated.

## Capabilities

### New Capabilities

- `deployment-storage-migration`: what the migration guarantees about the data,
  the claims and the deployment's power.

### Modified Capabilities

- `deployment-power-data-model`: the reason set gains `maintenance`.
- `deployment-power-api`: the maintenance hold, and its refusals.
- `deployment-power-ui`: the Maintenance label, and no actions while it lasts.
- `cli-power`, `cli-deploy`: the client explains a maintenance refusal.
- `deployment-storage-class`: the migration may change a recorded class.

## Impact

- One Alembic migration widens `ck_deployment_power_reason`.
- `freepod` 0.25.1. Older clients show the platform's message for the new code.
- No chart changes. A migrated volume keeps the old volume's root mode and
  owner, so a chart that relied on `local-path`'s world-writable root still
  works.
