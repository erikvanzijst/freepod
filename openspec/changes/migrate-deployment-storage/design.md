# Design

## Context

`deployment-storage-class` puts new deployments on Ceph RBD and leaves existing
ones untouched: `deployment.storage_class` is null for them, and the
post-renderer then leaves their claims as the chart renders them. Its design
left the move of existing volumes to this change, as the only writer of the
class after creation.

Facts that shape the move:

- A claim's class and access modes can't change. Neither can a StatefulSet's
  `volumeClaimTemplates`.
- Helm-owned claim names are fixed by the chart. StatefulSet claims are named
  `<template>-<statefulset>-<ordinal>`.
- RBD enforces a claim's size; `local-path` never did.
- A stopped deployment (`deployment-power-*`) runs nothing and keeps its
  claims, but its owner can start it or roll out a release at any time.
- Helm 4 recreates a release object that was deleted outside Helm on its next
  upgrade, under its own field manager.

## Goals / Non-Goals

**Goals:**
- Move one deployment at a time with only a short stop, verified, and
  resumable after any failure.
- Leave the deployment exactly as a deployment created on the new class would
  be: same claim names, the new class, `ReadWriteOncePod`, Helm owning its
  claims.
- Keep the old data until an operator deletes it, and be able to go back.

**Non-Goals:**
- Platform volumes (registry, object storage, databases). They are Terraform's,
  not a release's.
- Growing a claim during the move. The size is what the release renders.
- An API, `caelus` command or UI for the move.

## Decisions

### D1. A script in `api/bin`, run in the reconcile worker's pod

It runs once per deployment and never again, so it stays out of the API and
`caelus`. It uses the services and models in-process for the power ledger and
the class. It drives `kubectl` and `helm` as the reconciler does, and needs
the worker's image and service account.

- **Rejected: a `caelus` command.** That's a permanent surface for a one-off,
  and it would need tests and help text for its whole life.

### D2. Maintenance is a power reason

The script must keep the deployment stopped and unchanged for minutes. Power
already has the parts for that: a stopped render, a ledger and a reason, and
start already refuses reasons the owner can't lift.

- `begin_maintenance` records `stopped`/`maintenance` for the platform (actor
  null), whatever the current power. It is accepted only for a ready
  deployment with no open reconcile, so the power it replaces is the applied
  one.
- `end_maintenance` records the state and reason of the newest row outside
  maintenance that was applied without error, or `running`/`manual` when there
  is none. So a deployment its owner had stopped, or one stopped for payment,
  goes back to that stop. It is also accepted for a failed deployment. Nothing
  else can change it while it is held, and the operator must be able to let
  go.
- While held, start is refused with code `under_maintenance`, before the
  readiness check, so the owner learns the actual reason. Update is refused
  with the same code, checked again inside the guarded `UPDATE`, so a
  concurrent hold can't slip a release in. Stop is a no-op, as for any stopped
  deployment. Delete stays allowed: the owner can always leave, and the volumes
  the script kept outlive the namespace.
- **Rejected: no reason, just a stop.** The owner could start the app halfway
  through a copy, and the nightly upgrader could roll out a release halfway
  through a switch.
- **Rejected: a separate lock column.** That would add a second notion of
  "may this deployment change" beside power, and the dashboard would need to
  read it too.

### D3. Reserve, record, release, re-render

For each claim, the new volume is copied, then *reserved* for the claim's name:
its `claimRef` names the claim, with no `uid`. The switch then:

1. records the class;
2. deletes, with orphan cascade, every StatefulSet with claim templates (none
   has pods while stopped);
3. deletes each claim that is not already on its new volume, after setting
   that volume to `Retain`;
4. enqueues a reconcile: the stopped render with the class creates the Helm
   claims and the StatefulSets;
5. creates each missing StatefulSet claim from its recreated template, naming
   the reserved volume;
6. checks that every claim is bound to the volume reserved for it;
7. ends maintenance.

A reserved volume stays `Available` while a claim of that name exists and is
bound elsewhere, and only a claim of that name binds it. So at any crash point
a reconcile either renders the old claims against the old volumes, or renders
the new ones against the reserved copies. The worst outcome is a failed
reconcile, never a freshly provisioned empty volume. Recording the class before
deleting anything keeps that true even if the owner deletes the deployment, or
something else enqueues a reconcile, in between.

- **Why the release creates its own claims.** A claim written by hand would be
  owned by another field manager. The first plan change that grows it would
  then fail the release with a server-side apply conflict.
- **Why the script creates StatefulSet claims.** A stopped StatefulSet creates
  none, and the binding has to be checked before the deployment is released.
  StatefulSet claims aren't Helm's, and the controller adopts an existing claim
  of the right name. The script copies the template's labels and annotations
  and the StatefulSet's selector labels, as the controller would.

### D4. Copy with rsync in a pod beside the data

A pod in the deployment's namespace mounts the old claim read-only and a
temporary claim on the new class. It runs as root with the default
capabilities, which the tenant namespaces' baseline pod security allows. The
scheduler places it on the old volume's node.

- `rsync -aHAX --numeric-ids --delete` copies ownership, modes, hard links,
  ACLs and xattrs, including the root directory's mode. `--delete` also drops
  the new filesystem's empty `lost+found`. So no chart fix from
  `deployment-storage-class` is needed for a migrated volume.
- A second pass with `-c --dry-run --itemize-changes` must report nothing.
- The image is pinned by digest.
- On a rerun the copy is re-synced, never trusted: the deployment may have run
  since.

### D5. Sizes come from the render

The new claim gets the size the release renders: that's what Helm will apply,
and Kubernetes refuses to shrink a claim. Before stopping anything, the script
measures each volume and refuses one using more than 80% of its rendered size.
That leaves room for the filesystem and the 5% ext4 keeps for root, which an
app running as another user can't use. The copy pod then checks the new
volume's real free space. A claim that is too small has to be grown in the
chart or plan first.

### D6. Nothing is deleted until cleanup

The old volume is kept with `Retain` and labeled with the deployment, its role
and the claim it belonged to. `rollback` reserves those volumes again and runs
the same switch with no class. The Ceph copies it releases are kept the same
way. `cleanup` sets `Delete` on released volumes older than a cutoff, and
their provisioners delete the data.

### D7. Every run starts from what it finds

Every run works out its state from the labels, the claims and the deployment's
power. It doesn't keep a log of its own. A session advisory lock on the
deployment id keeps two runs apart. A failure before the class is recorded ends
maintenance, so the app comes back. A failure after it leaves the deployment
held, and rerunning `migrate` or `rollback` finishes the switch.

## Risks / Trade-offs

- **Downtime.** It lasts for the copy of the deployment's data plus two
  reconciles. The data is in the low gigabytes per deployment.
- **The backup changes with the class.** A host-level backup of the node no
  longer contains a migrated deployment's data. → The environment needs a
  backup of the new class before production deployments move.
- **A start that fails after the switch** leaves the deployment failed and
  held, with both copies kept. → Rerun `migrate` once the cause is fixed, or
  roll back.
- **A long `kubectl exec` session can drop.** → The run resumes when started
  again (D7).
