# Tasks

## 1. Data model and settings

- [x] 1.1 Add nullable `storage_class` columns to `user` and `deployment` in one Alembic migration. Add them to `UserORM` and `DeploymentORM`, with no backfill (design D1). Verify `alembic upgrade head` and `downgrade -1` round-trip on the test database, and that existing rows read null.
- [x] 1.2 Add `storage_classes: list[str] = []` to `app/config.py` (design D5). Verify with a settings test that `CAELUS_STORAGE_CLASSES='["ceph-freepod-dev"]'` parses into the list.

## 2. Selection at create

- [x] 2.1 In `create_deployment`, set `storage_class` from the owner's `user.storage_class`, or null. Refuse a class that isn't in `storage_classes` before anything is flushed, with an error naming the class (spec: The class is chosen once; Only allowed classes are chosen). Verify with service tests for each case:
  - a flagged account;
  - an unflagged account;
  - an administrator creating for a flagged owner;
  - an unlisted class, including on an empty list (no deployment, release or subscription rows left behind).
- [x] 2.2 Verify through the REST API and `caelus` that a `storage_class` field on create or update has no effect, and that no deployment or user read model carries one (spec: The class never changes through the API). Also verify that a template move, a vars update and stop/start leave the column unchanged. Add the tests to the existing deployment test modules.

## 3. Post-renderer storage step

- [x] 3.1 Add `--storage-class` to `app/post_render.py`. When it's given, every `PersistentVolumeClaim` and every StatefulSet `volumeClaimTemplates[]` entry gets `spec.storageClassName` set to the class and `spec.accessModes` set to `[ReadWriteOncePod]`, overriding the chart's class (design D2, D3). Update the module docstring's list of steps. Verify in `test_post_render.py`:
  - a standalone claim and a claim template are both rewritten;
  - a chart-named class is overridden;
  - documents without claims pass through byte for byte.
- [x] 3.2 Make the step exit non-zero, with a message naming the claim, when any of the following holds (design D4):
  - a release claim is mounted by two pod templates;
  - it's mounted by a Deployment with more than one replica, or a strategy other than `Recreate`;
  - it's mounted by name by a StatefulSet with more than one replica;
  - a claim requests an access mode other than `ReadWriteOnce`.

  Claims the release doesn't render are neither checked nor rewritten. Verify with one test per refusal, plus one where a pre-existing claim is mounted.
- [x] 3.3 Verify that without `--storage-class` the output is unchanged for a chart with claims and claim templates, and that `--render=stopped` with `--storage-class` keeps the class and RWOP (spec: The class is applied in every render). Add the stopped case to `test_chart_stopped_render.py`.
- [x] 3.4 Pass the deployment's `storage_class` from `reconcile.py` to `helm_upgrade_install`. Have it add `--post-renderer-args --storage-class=<name>` only when the class is set. Verify with provisioner and reconcile tests asserting the Helm command with and without a class.
- [x] 3.5 Add a "Storage class" architecture note to `AGENTS.md`. It should say the class is recorded at creation, applied by the post-renderer, and never changed through the API, and link the new specs. Verify the links resolve.

## 4. Chart contract and Postgres fix

- [x] 4.1 Add `api/tests/test_chart_storage_contract.py`, discovering charts the way `test_chart_rollout_strategy.py` does. It should assert that every claim and claim template:
  - names no class and requests `ReadWriteOnce` with default values;
  - is mounted by exactly one pod template;
  - is mounted by no workload rendering more than one replica.

  It should also pipe each chart's render through the post-renderer with `--storage-class`, so a chart the step would refuse fails here. Exempt helloworld, with its reason. Verify the module passes, and that it fails against a copy of a chart with a second workload mounting its claim.
- [x] 4.2 Add an init container to the Postgres pods of the immich, immich-sso and openproject charts (design D6). It uses the Postgres image and runs `rmdir <PGDATA>/lost+found 2>/dev/null || true`. Extend each chart's test module to render it. Verify with Docker against the chart's own image that:
  - a data directory holding only an empty `lost+found` initializes;
  - one holding an existing cluster at its root starts on it;
  - one with files in `lost+found` starts on its data.
- [x] 4.3 Bump immich to 0.3.1, immich-sso to 0.1.5 and openproject to 0.2.1. Point `products/catalog/immich` and `products/catalog/openproject` at the new versions. Verify that `helm lint` passes and that `test_catalog_charts.py` and the catalog format tests pass.
- [x] 4.4 Run the full `api/` suite (`-n 8`) and verify it is green.
- [x] 4.5 Give Mattermost's server pod `fsGroup: 2000` and `fsGroupChangePolicy: OnRootMismatch` (design D8). Extend the chart's tests to render it. Bump mattermost to 1.1.8 and point `products/catalog/mattermost` at it. Verify `helm lint` and the catalog tests pass.
- [x] 4.6 Add the empty-`lost+found` init container to Docmost's Redis pod (design D6), running `rmdir /data/lost+found 2>/dev/null || true` with the Redis image. Extend the chart's tests to render it. Verify with Docker against `redis:8` that Redis starts and writes its append-only files on a data directory holding only an empty `lost+found`, and starts on an existing one. Bump docmost to 0.1.4 and point `products/catalog/docmost` at it. Verify `helm lint` and the catalog tests pass.
- [x] 4.7 Re-run the full `api/` suite (`-n 8`) and verify it is green.

## 5. Terraform and node operations

- [x] 5.1 Add a `storage_classes` variable to `tf/app/caelus`, defaulting to empty, and map it to `CAELUS_STORAGE_CLASSES` (JSON) in the configmap. Pass per-workspace values from `tf/app/main.tf`. Verify `terraform validate`, and that `terraform plan` in each workspace shows only the configmap change.
- [x] 5.2 Add a volume-filling alert in `tf/deps/prometheus` from kubelet volume stats, firing when a volume has less than 15% free for 15 minutes (design: Risks, sizes become real). Verify `terraform validate`, and that the expression returns series for an RBD volume on dev.
- [x] 5.3 Write `tf/deps/ceph-csi/README.md` (design D7). It covers:
  - the kernel requirement for `aes256k` cephx keys;
  - the node shutdown unit (ordered `After=network-online.target`, `ExecStop` running `k3s-killall.sh`) and how to install it;
  - that a crash needs no action, while an orderly shutdown needs the unit.

  Verify the install steps match what is installed in 7.2.

## 6. Dev rollout

- [x] 6.1 Publish the three Postgres chart releases, apply the catalog to dev, and add the immich-sso template on dev by hand. Move the dev immich, immich-sso and openproject deployments to the new templates. Verify each Postgres starts on its existing data.
- [x] 6.2 Apply `tf/app` on dev with `storage_classes = ["ceph-freepod-dev"]`. Flag the operator's dev account with `ceph-freepod-dev` in SQL from the API pod. Verify that a new deployment from that account records `ceph-freepod-dev`, that one from an unflagged account records null, and that flagging an account with `ceph-freepod` on dev makes its create fail.
- [x] 6.2a Publish mattermost 1.1.8 and docmost 0.1.4, and roll the catalog out to dev with an API image that carries it. Verify dev's Mattermost and Docmost templates point at the new versions.
- [x] 6.3 From the flagged dev account, create one deployment of every catalog product and of immich-sso. Verify for each that:
  - its claims are on `ceph-freepod-dev` with `ReadWriteOncePod`;
  - every pod starts;
  - the app serves its first page and persists a write across a pod restart;
  - each container that writes to a claim can write to it as its own user.

  Record the results.

  Results (dev, 2026-11-11): every catalog product and immich-sso meets all four.
  - Matrix's image has no shell, so it was checked by its data files surviving the restart.
  - App Studio's first page answers 401, its sign-in.
  - Custom renders no claims.
  - The first run found Mattermost unable to write as uid 2000 and Docmost's Redis unable to write behind `lost+found`; both pass on mattermost 1.1.8 and docmost 0.1.4 (4.5, 4.6).
  - OpenProject's first install once outran Helm's 300 s wait while four other first installs ran beside it; alone it finished in 3.5 minutes.
- [x] 6.4 On one product with an in-chart database, exercise:
  - stop and start;
  - a vars edit;
  - a template move;
  - deleting the database pod (the replacement waits for the old one);
  - deleting the deployment.

  Verify each succeeds, and that the RBD images are gone afterwards (`rbd ls freepod-dev`).
- [x] 6.5 In a dev App Studio instance on Ceph under gVisor, create a project and have the agent write files. Restart the pod and verify the files are intact.

## 7. Node shutdown drill (maintenance window, both environments affected)

- [ ] 7.1 With a dev RBD volume mounted on the tenant node and no unit installed, reboot the node, ready to hard-reset it from the hypervisor. Record whether the shutdown hangs, and for how long.
- [ ] 7.2 Install the shutdown unit on both nodes, as documented in 5.3. Reboot each with RBD volumes mounted. Verify:
  - each shutdown completes without a hang;
  - every pod is running again afterwards, with its volume mounted.

## 8. Prod rollout

- [ ] 8.1 Apply the catalog to prod and add the immich-sso template by hand. Move the prod immich, immich-sso, openproject, mattermost and docmost deployments to the new templates. Verify each Postgres starts on its existing data, and that Mattermost and Docmost still read and write theirs.
- [ ] 8.2 Apply `tf/app` on prod with `storage_classes = ["ceph-freepod"]`. Verify a new deployment by an unflagged account records null.
- [ ] 8.3 Flag the operator's account with `ceph-freepod` in SQL from the API pod. Create a deployment and verify that its claims are on `ceph-freepod` with `ReadWriteOncePod` and that the app serves.

## Workflow follow-up

- Archive the change and sync its specs after prod verification. Then repoint the change links in AGENTS.md ("Storage class") and `tf/deps/ceph-csi/README.md` at the synced specs and the archived design.
- Update the local storage architecture notes (phase 4: post-renderer, not chart system values) and the migration order: deployments, then the registry, Garage, tenant Postgres, and finally the platform database and Keycloak.
