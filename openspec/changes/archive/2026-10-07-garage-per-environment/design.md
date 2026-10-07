## Context

Garage ran as a `tf/deps` singleton (namespace `garage`, `blob.freepod.eu`) with buckets
`dev` and `prod`, keys `caelus-api-dev` / `caelus-api-prod`, and one `dep-<uuid>` bucket
plus `app-<uuid>` key per storage-enabled deployment of either environment. At migration
time it held 50 buckets (18 live tenant buckets: 3 dev, 15 prod) and about 88 MB of
objects. The k3s node had 55 GB free.

Prod tenant data must not be lost, and prod tenants should not notice the move.

## Goals / Non-Goals

**Goals:**

- Each environment owns a Garage instance that the other cannot reach or administer.
- No prod object lost and no prod tenant credential changed.
- The migration is rehearsed end to end on dev with real data before prod is touched.

**Non-Goals:**

- Moving tenant traffic to an in-cluster endpoint. Pods still reach Garage by hairpin
  through the public hostname, which keeps the build NetworkPolicy unchanged.
- Changing tenant bucket naming, quotas or reclamation.

## Decisions

### D1. A new instance per environment, populated by copy, rather than re-homing the old one

Re-homing the existing StatefulSet into `tf/app`'s prod workspace would mean moving state
between two root modules and rebinding `local-path` volumes into a different namespace,
all on the only copy of prod data. Both of those volumes had reclaim policy `Delete`, so
any mistake that deleted the `garage` namespace would have deleted the data. Copying
88 MB is cheap and leaves the old instance intact as a rollback.

### D2. Original access keys are imported, not re-minted

`ImportKey` exists for exactly this (migration and restore). Importing each deployment's
`app-<uuid>` key before anything reconciles against the new instance means the
reconciler's find-by-name returns the same key and secret, so the tenant Secret is
unchanged. If a reconcile ran first, it would mint a new key, write it into the tenant
Secret while `blob.freepod.eu` still pointed at the old instance, and any pod restarting
in that window would come up with a key the old instance rejects. The migration script
refuses to proceed if the destination already holds a different key under a deployment's
key name.

### D3. One platform bucket and key per instance: `artifacts` / `caelus-api`

Environment-qualified names only made sense on a shared instance. The platform bucket
is named for what it holds (build artifacts); tenant buckets keep their `dep-` prefix,
so the two cannot collide.

### D4. Admin token and RPC secret are generated into Terraform state

Nothing outside the instance needs either value, so `random_password` / `random_id`
replace the operator-supplied tfvars, following `tf/app/caelus/tenant-db.tf`. The
`tf/deps` → `tf/app` credential-pasting step disappears because the module's outputs are
wired into `module.caelus` directly.

### D5. A temporary per-workspace `garage_cutover` switch

One flag per workspace moved both the Ingress and the API's wiring (S3 endpoint,
bucket, key, admin URL and token) in the same apply. Two Ingresses claiming one host in
different namespaces leave Traefik's choice undefined, so prod's new Ingress was created
only after the `tf/deps` one was removed (`tf/deps` gained an `ingress_enabled`
variable for this). The switch was removed along with the old instance.

### D6. A credential change restarts its consumers

The API, worker and build worker read `caelus-s3` through `env_from`, but only the API
ConfigMap had a checksum annotation, so a changed key or endpoint was not picked up
until an unrelated restart. A `checksum/s3` annotation now rolls all three.

Tenant pods have the same property: the custom chart reads the object-storage Secret
through `envFrom`, and a reconcile that rewrites it does not roll the pod. Prod avoided
the need by keeping Secrets identical (D2); dev's endpoint change required an explicit
`kubectl rollout restart` per tenant namespace.

## Migration (as run on 2026-10-07)

0. Set both old PVs to `Retain`. Back up into `var/garage/backup-<ts>/`: a JSON dump of
   every bucket and key (with secrets), an `rclone` export of every bucket (checked),
   and a tarball of both volume directories taken with the StatefulSet scaled to 0.
1. Apply the module in both workspaces with `garage_cutover` off; bootstrap each layout.
2. Dev: `var/garage/migrate.sh --env dev --dst-ns caelus-garage-dev --db-ns caelus-dev`.
   It selects live deployments from the environment's own database that have an
   `app-<id>` key on the source, imports keys, creates buckets, grants, copies quotas,
   CORS and lifecycle, copies objects with `rclone --metadata` and runs `rclone check`.
   The source `dev`/`prod` bucket's objects go to `artifacts`.
3. Dev cutover (`garage_cutover.default = true`), reconcile the three dev deployments
   (Secrets differed only in endpoint), restart tenant pods, run `migrate.sh --catchup`,
   verify kanban.fred attachments are served from `blob.dev.freepod.eu`.
4. Prod: apply, migrate, then back-to-back apply of `tf/deps` (Ingress removed) and
   `tf/app` prod (`garage_cutover.prod = true`), then `migrate.sh --catchup`
   (`--ignore-existing`, so nothing written to the new instance is overwritten),
   reconcile all 15 storage deployments, and verify upgrader.prutser from inside its pod.

## Risks / Trade-offs

- [Writes to the old instance between the copy and the Ingress switch] → the catch-up
  pass copies anything missing; an object deleted in that window would reappear.
- [Two more PVC pairs on a node without quota enforcement] → the data PVC stays capped at
  20Gi each; actual usage is megabytes.
- [Losing the old instance removes the rollback] → removed only after a final catch-up
  pass found nothing missing; the backup in `var/garage/` (metadata, objects and a
  volume tarball) remains the way back.
