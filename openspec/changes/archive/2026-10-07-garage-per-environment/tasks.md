## 1. Safety net

- [x] 1.1 Set the old instance's two PVs to reclaim policy `Retain`
- [x] 1.2 Back up into `var/garage/backup-<ts>/`: metadata JSON (buckets, keys with secrets, layout, admin tokens), an `rclone` export of every bucket checked against the source, and a tarball of both volumes taken with the StatefulSet scaled to 0

## 2. Per-environment module

- [x] 2.1 Add `tf/app/garage/`, derived from `tf/deps/garage/`: `host` instead of `domain`, an `ingress_enabled` switch, generated admin token and RPC secret (design D4)
- [x] 2.2 Provision one platform bucket `artifacts` and key `caelus-api` per instance, replacing the `environments` list (design D3)
- [x] 2.3 Add namespace `caelus-garage` / `caelus-garage-dev`, reserve `blob.dev.freepod.eu` in dev, and the temporary `garage_cutover` switch (design D5)
- [x] 2.4 Add `checksum/s3` to the API, worker and build worker so a credential change rolls them (design D6)
- [x] 2.5 Apply in both workspaces with the switch off and bootstrap both cluster layouts

## 3. Dev

- [x] 3.1 Run `var/garage/migrate.sh` for dev before any reconcile; re-run to confirm it is a no-op
- [x] 3.2 Switch dev over; verify the API's endpoint, bucket and key
- [x] 3.3 Reconcile the three storage deployments; verify Secrets changed only in endpoint and no key was minted; restart tenant pods; run the catch-up pass
- [x] 3.4 Verify kanban.fred.dev.freepod.eu serves every attachment from `blob.dev.freepod.eu`

## 4. Prod

- [x] 4.1 Migrate the 15 storage deployments and the artifact bucket
- [x] 4.2 Remove the `tf/deps` Ingress and switch prod over, back to back; run the catch-up pass
- [x] 4.3 Reconcile all storage deployments; verify every tenant Secret is byte-identical to before
- [x] 4.4 Verify upgrader.prutser.freepod.eu lists and serves its files through the new instance

## 5. Documentation

- [x] 5.1 Update `tf/README.md`, `tf/app/README.md`, `tf/deps/README.md`, `api/README.md` and `AGENTS.md`

## 6. Remove the shared instance

- [x] 6.1 Remove `module.garage`, the `garage` namespace, its outputs and variables from `tf/deps`, and `tf/deps/garage/`
- [x] 6.2 Remove `garage_cutover`, `s3_endpoint_url`, `s3_buckets`, `s3_access_key_ids`, `s3_secret_access_keys`, `garage_admin_url` and `garage_admin_token` from `tf/app`, and the matching `secrets.auto.tfvars` entries
- [x] 6.3 Delete the two retained PV objects and their directories under `/var/lib/rancher/k3s/storage/` on the node
- [x] 6.4 Run a final catch-up pass for both environments before destroying, confirming nothing on the old instance is missing from the new ones
