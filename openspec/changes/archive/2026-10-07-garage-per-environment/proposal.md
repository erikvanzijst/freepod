## Why

Garage was set up as one instance in `tf/deps` serving both dev and prod, separated only
by bucket and access-key naming. That puts dev experiments, upgrades and mistakes on the
same store, and the same admin token, as prod's tenant data: the API in each environment
holds an admin credential that can list, read keys for and reconfigure every bucket of
the other environment. Every other per-environment concern already lives in the
workspace-multiplexed `tf/app`, so the shared store is the odd one out, and its
separation exists only by convention.

## What Changes

- Garage moves to `tf/app/garage/`, one instance per workspace: namespace
  `caelus-garage-dev` at `blob.dev.freepod.eu` and `caelus-garage` at
  `blob.freepod.eu`. The two share nothing: not data, not admin tokens, not RPC
  secrets.
- Each instance generates its own admin token and RPC secret into Terraform state; the
  operator no longer creates them or pastes credentials from `tf/deps` outputs into
  `tf/app/secrets.auto.tfvars`. The API is wired from the module's outputs directly.
- Each instance provisions one platform bucket, `artifacts`, with one key,
  `caelus-api`. The per-environment `dev`/`prod` bucket and `caelus-api-<env>` key
  naming goes away along with the list of environments it was keyed on.
- Changing the API's S3 credentials restarts the pods that read them (API, worker,
  build worker), which it previously did not.
- Existing data is migrated with the deployments' original access keys imported into the
  new instance, so tenant credentials are byte-identical and no tenant pod needs to
  change for prod. Dev's endpoint changes, so dev tenants restart once.
- **BREAKING (dev only):** dev deployments' `AWS_ENDPOINT_URL` changes from
  `https://blob.freepod.eu` to `https://blob.dev.freepod.eu`.
- The `tf/deps` instance and its volumes are removed, together with the temporary
  `garage_cutover` switch and the variables that carried credentials across from
  `tf/deps`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `garage-object-store`: one instance per environment in `tf/app` replaces the shared
  `tf/deps` singleton; admin secrets are generated, not supplied.
- `garage-bucket-provisioning`: one platform bucket and key per instance replaces
  per-environment naming; credentials reach the API from module outputs, and a
  credential change restarts its consumers.
- `garage-s3-edge`: the endpoint is `blob.<environment domain>`, not `blob.freepod.eu`
  for both.

## Impact

- Terraform: new `tf/app/garage/` module, `kubernetes_namespace.garage`, `checksum/s3`
  annotations in `tf/app/caelus/`; `tf/deps` loses the Garage module, namespace,
  outputs and secrets.
- Tenants: none in prod. Dev `custom` deployments see a new endpoint after one
  reconcile and restart.
- Operations: one cluster-layout bootstrap per instance; two more PVC pairs on the node
  (each data PVC is capped at 20Gi).
- Migration tooling lives in the gitignored `var/garage/` (`migrate.sh`), as it is
  one-off; its method is recorded in design.md.
