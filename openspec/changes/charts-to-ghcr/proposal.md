## Why

Every platform-owned container image — the API, the UI, the Keycloak build, the SSH
sidecar, the SSH auth resolver, the tenant build image — is published to ghcr.io by
`scripts/build-images.sh`, on immutable version tags, by CI, with a publishing path that
refuses to overwrite a version the registry already holds.

The Helm charts are not. Every product chart, and the `custom` placeholder image the
chart falls back to, is pushed by hand to the internal OCI registry from a developer
workstation. That leaves the platform's deployment path resting on artifacts that:

- **only exist on one unmanaged host**, reachable only from the LAN, with no backup and
  no way to rebuild them except by finding whoever last packaged the chart;
- **can be silently overwritten**, because nothing on that path enforces the
  no-re-push rule the ghcr-published images enforce in code;
- **cannot be published by CI at all**, since the host is unreachable from GitHub
  runners — so a chart release is a manual act with no record of who performed it;
- **require TLS verification to be disabled** on every push and on every pull, because
  the host serves a certificate for a name it is not addressed by. `helm push` carries
  `--insecure-skip-tls-verify` in nine product READMEs, and the reconciler passes the
  same flag for every OCI chart it installs.

Charts are the most privileged artifact the platform consumes: the reconciler renders
them into Kubernetes objects. They belong where the rest of the platform's artifacts
already are, published by the same path, under the same rules.

## What Changes

- **Every product chart is published to ghcr.io** under one path, on the immutable
  version tag declared in its `Chart.yaml`. Nine charts today: `custom`, `helloworld`,
  `immich`, `lemmy`, `matrix`, `mattermost`, `naas`, `nextcloud`, `vaultwarden`. The
  `ssh-sidecar` library chart is unaffected: it is a `file://` dependency vendored into
  each packaged chart and is published nowhere today.
- **The `custom` placeholder image is published to ghcr.io** alongside the other
  platform images, taking its tag from a `VERSION` file in its build context, the way
  the SSH sidecar, the SSH auth resolver and the build image already do.
- **A publishing path that refuses to overwrite.** Chart publishing becomes a script
  with the same contract as `build-images.sh`: publishing a version the registry already
  holds fails, `--skip-if-published` turns that into a no-op, and CI runs it on merge so
  a chart lands exactly when its version moves.
- **Charts and the placeholder are published at public visibility**, so the reconciler's
  `helm` pull and the kubelet's placeholder pull need no credential. They contain no
  secrets; a GHCR package is private by default and must be set once per package.
- **Catalog files and database-authored templates point at the new references.**
  Changing `chart_ref` changes a template's spec hash, so catalog reconciliation inserts
  a new template version rather than mutating the old one; existing deployments are
  re-pointed at it explicitly.
- **`--insecure-skip-tls-verify` is removed from the reconciler's Helm path** once no
  current or in-use template references the internal registry, and from the product
  READMEs with it.
- **The internal registry's `helm/*` and `caelus/*` repositories are retired** once no
  live deployment resolves a chart or a placeholder from them.

No tenant-visible behavior changes: a deployment keeps running its current chart until
it is re-pointed, and the re-point is an ordinary release.

## Capabilities

### New Capabilities
- `platform-artifact-publishing`: where platform-owned deployable artifacts — the
  product Helm charts and the platform images referenced by their default values — are
  published, on what tags, under what visibility, and what a consumer may reference.
  Covers the no-overwrite guarantee and the requirement that no platform artifact is
  served from an environment-local registry. Does not restate what any individual image
  contains; `ssh-sidecar-image` and the product charts keep their own specs.

### Modified Capabilities
<!-- None. `product-catalog-format` governs the shape of a catalog file, not the value
     of `chart_ref`; no existing requirement mandates a registry. -->

## Impact

- **Charts**: `products/*/chart/` (nine `Chart.yaml` version bumps and their
  `values.yaml` where a default image reference moves).
- **Images**: `products/custom/placeholder/` gains a `VERSION`;
  `scripts/build-images.sh` gains a `--placeholder` target.
- **Publishing**: a new chart publish script, and a step in
  `.github/workflows/ci.yml`'s `publish-images` job.
- **Catalog**: `products/catalog/{custom,immich,nextcloud,vaultwarden}.yaml` —
  `template.chart_ref`, and `system_values.placeholderImage` for `custom`.
- **Database**: templates for the non-curated products (`helloworld`, `lemmy`, `matrix`,
  `mattermost`, `naas`) are authored in the database and are updated through the
  operator CLI, not by catalog reconciliation.
- **Live deployments**: each is moved to the template version carrying the new
  `chart_ref`, one rolling release per deployment.
- **Code**: `api/app/provisioner.py` — the OCI branch that adds
  `--insecure-skip-tls-verify`.
- **Docs**: the "Build and publish" section of each product README, and
  `products/custom/README.md`'s placeholder instructions.
