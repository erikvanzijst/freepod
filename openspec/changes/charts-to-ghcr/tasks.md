## 1. Publishing path

- [ ] 1.1 Add `products/custom/placeholder/VERSION` holding `0.1.0`, and a `--placeholder` target to `scripts/build-images.sh` that derives its tag from that file, refuses to overwrite an already-published version, and honors `--skip-if-published` — verify by reading the script's help output and confirming the target follows the same shape as `--builder`
- [ ] 1.2 Add `scripts/publish-charts.sh` that packages and pushes one or all product charts to `oci://ghcr.io/<owner>/freepod/charts`, taking each tag from that chart's `Chart.yaml` version, running `helm dependency build` for charts with dependencies, refusing to overwrite a published version, and supporting `--skip-if-published` — verify `./scripts/publish-charts.sh --help` lists every chart under `products/*/chart` and excludes `products/_lib/`
- [ ] 1.3 Add a test asserting that every catalog file's `template.chart_ref` names the ghcr.io charts path and that its `template.chart_version` equals the `version` in the corresponding `products/<slug>/chart/Chart.yaml` — verify `cd api && uv run --no-sync pytest` passes and the test fails when a chart version is bumped without the catalog following
- [ ] 1.4 Add publish steps for the placeholder and the charts to the `publish-images` job in `.github/workflows/ci.yml`, both with `--skip-if-published` — verify a merge to `master` with no version change leaves both steps reporting nothing to publish

## 2. First publication

- [ ] 2.1 Publish the placeholder image with `./scripts/build-images.sh --placeholder`, set the new GHCR package to public, and verify `docker pull ghcr.io/<owner>/freepod/custom-placeholder:0.1.0` succeeds from a context holding no GHCR credentials
- [ ] 2.2 Publish all nine product charts with `./scripts/publish-charts.sh`, set each new GHCR package to public, and verify `helm show chart oci://ghcr.io/<owner>/freepod/charts/<name> --version <version>` succeeds for each from a context holding no GHCR credentials
- [ ] 2.3 Re-run both publish commands without `--skip-if-published` and verify each refuses to overwrite, then re-run with the flag and verify each is a no-op that exits zero

## 3. Curated products

- [ ] 3.1 Bump `products/custom/chart/Chart.yaml` to the next version and repoint `placeholderImage` in `chart/values.yaml` at the ghcr.io image, then publish that chart version — verify `cd api && uv run --no-sync pytest api/tests/test_custom_chart.py` passes and `helm template` renders the new placeholder reference with no `image` set
- [ ] 3.2 Update `template.chart_ref` in `products/catalog/{immich,nextcloud,vaultwarden}.yaml` to the ghcr.io path, and in `products/catalog/custom.yaml` update `chart_ref`, `chart_version` and `system_values.placeholderImage` together — verify `caelus catalog lint` passes
- [ ] 3.3 Roll out so catalog reconciliation runs, and verify each of the four products gained exactly one new template version whose `chart_ref` names ghcr.io, with the previous version still present

## 4. Database-authored products

- [ ] 4.1 List the live templates for `helloworld`, `lemmy`, `matrix`, `mattermost` and `naas`, and record for each the `chart_ref` and `chart_version` in use — verify the recorded set accounts for every non-curated product that has at least one deployment
- [ ] 4.2 Create a new template version per product through `caelus create-template`, identical to the one in use except for the ghcr.io `chart_ref` — verify `caelus list-templates <product_id>` shows the new version and `helm show chart` resolves the reference it names

## 5. Deployment migration

- [ ] 5.1 Enumerate live deployments grouped by product and template version, and record which template version each must move to — verify the enumeration covers every deployment that is not deleted
- [ ] 5.2 Move each deployment to its product's new template version and verify it reaches `ready` and serves traffic, one product at a time, starting with a single deployment per product before the rest
- [ ] 5.3 Verify no live deployment's rendered pod spec references the internal registry for its chart-default image, and that `custom` deployments with no build serve the ghcr.io placeholder

## 6. Retirement

- [ ] 6.1 Audit that no product template — curated or database-authored, including any backing `hello-static`, `nextcloud-wrapper` or `vaultwarden-wrapper` — and no live deployment still names the internal registry for a chart or a chart-default image; migrate or deliberately retire anything the audit surfaces, and verify the audit comes back empty before continuing
- [ ] 6.2 Remove `--insecure-skip-tls-verify` from the OCI branch in `api/app/provisioner.py` — verify `cd api && uv run --no-sync pytest` passes and a reconcile installs a ghcr.io chart with verification enabled
- [ ] 6.3 Update the "Build and publish" section of each product README and the placeholder instructions in `products/custom/README.md` to the new commands, with no `--insecure-skip-tls-verify` and no internal-registry reference — verify `grep -rn "registry.home/helm\|caelus/custom-placeholder" products/` returns nothing
- [ ] 6.4 Delete the `helm/*` and `caelus/*` repositories from the internal registry — verify its catalog no longer lists them and that a subsequent reconcile of one deployment per product still succeeds
