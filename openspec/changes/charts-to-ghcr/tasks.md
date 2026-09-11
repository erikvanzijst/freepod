## 1. Publishing path

- [x] 1.1 Add `products/custom/placeholder/VERSION` holding `0.1.0`, and a `--placeholder` target to `scripts/build-images.sh` that derives its tag from that file, refuses to overwrite an already-published version, and honors `--skip-if-published` — verify by reading the script's help output and confirming the target follows the same shape as `--builder`
- [x] 1.2 Add `scripts/publish-charts.sh` that packages and pushes one or all product charts to `oci://ghcr.io/<owner>/freepod/charts`, taking each tag from that chart's `Chart.yaml` version, running `helm dependency build` for charts with dependencies, refusing to overwrite a published version, and supporting `--skip-if-published` — verify `./scripts/publish-charts.sh --help` lists every chart under `products/*/chart` and excludes `products/_lib/`
- [x] 1.3 Add a test asserting that every catalog file's `template.chart_ref` names the ghcr.io charts path and that its `template.chart_version` equals the `version` in the corresponding `products/<slug>/chart/Chart.yaml` — verify `cd api && uv run --no-sync pytest` passes and the test fails when a chart version is bumped without the catalog following
- [ ] 1.4 Add publish steps for the placeholder and the charts to the `publish-images` job in `.github/workflows/ci.yml`, both with `--skip-if-published` — verify a merge to `master` with no version change leaves both steps reporting nothing to publish

## 2. First publication

- [x] 2.1 Publish the placeholder image with `./scripts/build-images.sh --placeholder`, set the new GHCR package to public, and verify `docker pull ghcr.io/<owner>/freepod/custom-placeholder:0.1.0` succeeds from a context holding no GHCR credentials
- [x] 2.2 Publish all nine product charts with `./scripts/publish-charts.sh`, set each new GHCR package to public, and verify `helm show chart oci://ghcr.io/<owner>/freepod/charts/<name> --version <version>` succeeds for each from a context holding no GHCR credentials
  - `custom` was published only at 0.9.2 (task 3.1), never at 0.9.1: no template would reference 0.9.1 on ghcr.io, and its default `placeholderImage` names the internal registry this change retires
- [x] 2.3 Re-run both publish commands without `--skip-if-published` and verify each refuses to overwrite, then re-run with the flag and verify each is a no-op that exits zero

## 3. Curated products

- [x] 3.1 Bump `products/custom/chart/Chart.yaml` to the next version and repoint `placeholderImage` in `chart/values.yaml` at the ghcr.io image, then publish that chart version — verify `cd api && uv run --no-sync pytest api/tests/test_custom_chart.py` passes and `helm template` renders the new placeholder reference with no `image` set
- [x] 3.2 Update `template.chart_ref` in `products/catalog/{immich,nextcloud,vaultwarden}.yaml` to the ghcr.io path, and in `products/catalog/custom.yaml` update `chart_ref`, `chart_version` and `system_values.placeholderImage` together — verify `caelus catalog lint` passes
- [ ] 3.3 Roll out so catalog reconciliation runs, and verify each of the four products gained exactly one new template version whose `chart_ref` names ghcr.io, with the previous version still present
  - dev (2026-09-11): rolled out as `api:charts-to-ghcr-dev`; catalog inserted exactly one row each — custom 93→100, immich 99→101, nextcloud 98→102, vaultwarden 96→103 — all on ghcr.io, previous rows present; prod pending

## 4. Database-authored products

- [ ] 4.1 List the live templates for `helloworld`, `lemmy`, `matrix`, `mattermost` and `naas`, and record for each the `chart_ref` and `chart_version` in use — verify the recorded set accounts for every non-curated product that has at least one deployment
  - dev (2026-09-11): Hello World tpl 97 `helloworld` 0.2.1 (2 deployments); Matrix tpl 38 `matrix` 0.1.6 (0); Mattermost tpl 82 `mattermost` 1.0.15 (0); Lemmy tpl 81 `lemmy` 0.4.3 (0); NaaS has no product row. Mattermost and Lemmy trail the repo (1.1.1, 0.5.1), so on dev they move to the repo versions rather than to an address-only copy; prod not yet inspected
- [ ] 4.2 Create a new template version per product through `caelus create-template`, identical to the one in use except for the ghcr.io `chart_ref` — verify `caelus list-templates <product_id>` shows the new version and `helm show chart` resolves the reference it names
  - dev (2026-09-11): created and made current with `update-product --template-id` (not in the task text, but required for new deployments to land on it) — Hello World 97→104, Matrix 38→105, Mattermost 82→106 (1.0.15→1.1.1), Lemmy 81→107 (0.4.3→0.5.1); system values and schema identical to the source rows; all refs resolve from the dev worker pod without credentials; prod pending

## 5. Deployment migration

- [ ] 5.1 Enumerate live deployments grouped by product and template version, and record which template version each must move to — verify the enumeration covers every deployment that is not deleted
  - dev (2026-09-11): 8 live, all `ready`, desired = applied — Custom user app 4 on tpl 93, Hello World 2 on tpl 97, Nextcloud 1 on tpl 98, Vaultwarden 1 on tpl 96; prod not yet inspected
- [ ] 5.2 Move each deployment to its product's new template version and verify it reaches `ready` and serves traffic, one product at a time, starting with a single deployment per product before the rest
  - dev (2026-09-11): all 8 moved — Hello World ×2 →104, Vaultwarden →103, Nextcloud →102, Custom ×4 →100 — each `ready` and serving its pre-move HTTP status. Custom `b370d4d2` first failed: its Deployment's app `image` was co-owned by a `kubectl-set` field manager (a manual `kubectl set image`, 2026-08-31), which Helm 4's server-side apply will not override; `--atomic` rolled it back and it kept serving. Removing that managedFields entry and re-queuing fixed it; prod pending
- [ ] 5.3 Verify no live deployment's rendered pod spec references the internal registry for its chart-default image, and that `custom` deployments with no build serve the ghcr.io placeholder
  - dev (2026-09-11): no pod of the 8 runs a chart-default image from the internal registry (3 `registry.home/<uid>@sha256` images are tenant build output, out of scope); `b370d4d2`, which has no build, runs `ghcr.io/…/custom-placeholder:0.1.0` with no image pull secret; prod pending

## 6. Retirement

- [ ] 6.1 Audit that no product's current template and no template a live deployment desires or runs — curated or database-authored, including any backing `hello-static`, `nextcloud-wrapper` or `vaultwarden-wrapper` — and no live deployment still names the internal registry for a chart or a chart-default image (historical rows that are none of these are exempt); migrate or deliberately retire anything the audit surfaces, and verify the audit comes back empty before continuing
  - dev (2026-09-11, pre-migration): `hello-static` (2 rows) and `nextcloud-wrapper` (1 row) exist only as historical template rows that are neither current nor used by a live deployment; `vaultwarden-wrapper` is absent
  - dev (2026-09-11, post-migration): no live deployment's desired or applied template and no live product's current template names the internal registry; 88 dormant historical rows across 9 products still do, including deleted product 7 (`custom`, tpl 45)
- [x] 6.2 Remove `--insecure-skip-tls-verify` from the OCI branch in `api/app/provisioner.py` — verify `cd api && uv run --no-sync pytest` passes and a reconcile installs a ghcr.io chart with verification enabled
  - verified on dev (2026-09-11) as `api:charts-to-ghcr-dev2`: Hello World `5e6e006a` re-released with no TLS-skip flag in its helm command and reached `ready`. Lands on this branch, which therefore must not merge until the prod half of 6.1 comes back clean
- [x] 6.3 Update the "Build and publish" section of each product README and the placeholder instructions in `products/custom/README.md` to the new commands, with no `--insecure-skip-tls-verify` and no internal-registry reference — verify `grep -rn "registry.home/helm\|caelus/custom-placeholder" products/` returns nothing
- [ ] 6.4 Delete the `helm/*` and `caelus/*` repositories from the internal registry — verify its catalog no longer lists them and that a subsequent reconcile of one deployment per product still succeeds
