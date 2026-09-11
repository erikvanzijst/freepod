## Context

See [proposal.md](./proposal.md) § Why for motivation. The state this design has to work
with:

- **ghcr.io already holds every platform image** and already has the conventions this
  change extends: a `VERSION` file per artifact, an immutable tag, a publish that refuses
  to overwrite, and `--skip-if-published` so CI can run it on every merge
  (`scripts/build-images.sh`, `.github/workflows/ci.yml` § `publish-images`).
- **Nine product charts live in this repository** (`products/*/chart/`), each carrying its
  own `Chart.yaml` version. `products/_lib/ssh-sidecar-chart` is a library chart consumed
  as a `file://` dependency and vendored into the packaged archive; it is published
  nowhere and stays that way.
- **The internal registry also holds repositories with no source in this repository** —
  `helm/hello-static`, `helm/nextcloud-wrapper`, `helm/vaultwarden-wrapper` — which may
  or may not still back a database-authored template.
- **A template's identity includes its chart reference.** `spec_hash` in
  `api/app/services/catalog.py` covers `chart_ref`, `chart_version`, `chart_digest`,
  `system_values` and `values_schema`, and catalog reconciliation inserts a new template
  version when that hash changes rather than mutating the existing row. A deployment
  names its template by `desired_template_id` and keeps resolving the old row until it is
  updated.
- **Four products are curated** (`custom`, `immich`, `nextcloud`, `vaultwarden`) and are
  reconciled from `products/catalog/*.yaml`. The rest (`helloworld`, `lemmy`, `matrix`,
  `mattermost`, `naas`) are database-authored and are not reachable from a catalog file.
- **No catalog file pins `chart_digest`**, so charts resolve by version tag.

## Goals / Non-Goals

**Goals:**

- One publishing path for platform artifacts, runnable by CI, with the no-overwrite
  guarantee enforced in code.
- A migration with no tenant-visible interruption: every deployment keeps serving while
  it waits its turn.
- The internal registry's `helm/*` and `caelus/*` repositories genuinely retired, not
  merely unused.

**Non-Goals:**

- Publishing the `ssh-sidecar` library chart. It has no independent consumer; vendoring
  it into each packaged chart is what makes a product chart self-contained.
- Pinning `chart_digest` on any template. Digest pinning is a separate decision with its
  own consequences for how a chart update reaches deployments.
- Changing anything about how the internal registry serves tenant build output.
- Re-homing the platform images already on ghcr.io.

## Decisions

### D1: ghcr.io, under a `charts/` path segment

Charts are published to `oci://ghcr.io/<owner>/freepod/charts`, producing packages named
`freepod/charts/<chart>`; the placeholder image goes to
`ghcr.io/<owner>/freepod/custom-placeholder` alongside the other platform images. The
owner is derived the way `build-images.sh` already derives it, so nothing new is
hardcoded.

*Alternative considered:* publishing charts beside the images with no path segment
(`freepod/<chart>`). Rejected — the namespace is shared, so a chart and an image of the
same name would collide, and `custom` is exactly that case today. The segment also keeps
the GHCR package list legible: eleven chart packages do not bury six image packages.

*Alternative considered:* a chart repository (index.yaml on static hosting) instead of
OCI. Rejected — the reconciler already installs by OCI reference, and this would
introduce a second distribution mechanism to keep in sync.

### D2: A separate `scripts/publish-charts.sh`, not a target in `build-images.sh`

Chart publishing is `helm package` + `helm push`, versioned from `Chart.yaml`, with an
existence check that speaks OCI through helm. That shares its *contract* with
`build-images.sh` — immutable tag, refuse to overwrite, `--skip-if-published` for CI —
but none of its machinery.

*Alternative considered:* a `--charts` target inside `build-images.sh`. Rejected — the
script is docker-buildx shaped throughout, `--all` semantics do not extend to artifacts
whose versions move independently, and the two have no code in common beyond the
convention. The repository already keeps one script per concern.

### D3: The publish check is `helm show chart`, not a new tool

Whether a chart version is already published is answered by attempting to fetch it with
helm, which speaks OCI natively and is already a dependency of every path here.

*Alternative considered:* `crane manifest` or `oras manifest fetch`. Rejected — a new
tool in CI to answer a question helm answers, and a chart's manifest carries helm's own
config media type, which generic image tooling handles inconsistently.

### D4: Moving a chart does not bump its version

A chart that is unchanged is published to the new location under its existing version.
The artifact is identical; only its address changes, and a version bump would claim a
content change that did not happen.

Only `custom` bumps, because its content does change: its default `placeholderImage`
points at the new image location. Eight charts move at their current versions.

The consequence is that each product gets exactly **one** new template version out of
this change — from the `chart_ref` change alone, or for `custom` from `chart_ref`,
`chart_version` and `system_values` together.

### D5: The placeholder keeps version 0.1.0

The image content is unchanged, so it is published to ghcr.io under the version it
already carries, from a new `products/custom/placeholder/VERSION` file that becomes the
single source for its tag. The version is free on ghcr.io because the image has never
been published there.

This is the same rule as D4 applied to an image, and it keeps the two conventions
identical: a version file in the build context, a tag derived from it, never re-pushed.

### D6: Packages are made public at publication, not worked around with credentials

GHCR creates a new package private. Each of the eleven new packages has its visibility
set to public once, as part of publishing it the first time, and the publish task
verifies an anonymous pull before the reference is put into a template.

*Alternative considered:* keeping the packages private and configuring credentials — a
`helm registry login` for the reconciler and an `imagePullSecret` in every tenant
namespace for the placeholder. Rejected — that is a credential distributed to every
tenant namespace, plus a rotation obligation, to protect artifacts that contain nothing
secret and are built from a source tree whose contents are already known to their
consumers.

### D7: Migration is per-product, and retirement is last

For each product: publish the chart, point the template at it, move that product's
deployments to the new template version, verify. Only when no template and no live
deployment resolves from the internal registry are its `helm/*` and `caelus/*`
repositories removed.

Curated products move through their catalog file, which is the only writable path for
them; database-authored products get a new template version through the operator CLI.
Both produce a new template version rather than a mutation, which is what makes the
migration reversible per product: a deployment that misbehaves on the new template is
pointed back at the old one, which still resolves, because retirement has not happened
yet.

### D8: `--insecure-skip-tls-verify` is removed at the end, not made conditional

The reconciler passes the flag for every `oci://` chart reference. It is deleted in the
final step, once no template names the internal registry.

*Alternative considered:* making it conditional on the chart host, so it could be removed
from the ghcr path immediately. Rejected — a rule whose only purpose is to expire, and
whose condition names one host, is more code and more review surface than deleting the
flag one step later. During the migration the flag applies to ghcr.io references it is
not needed for, which is harmless: ghcr.io's certificate verifies either way.

## Risks / Trade-offs

- **A deployment left on an old template after retirement would fail to reconcile** →
  Retirement is gated on an explicit audit: no template row, curated or not, and no live
  deployment may name the internal registry. The audit is a task, not a judgment call.
- **A package left private fails closed and confusingly** — `helm pull` returns 401 and a
  kubelet pull returns `ImagePullBackOff` → Each publish task verifies an anonymous pull
  from a context with no credentials before the reference is used.
- **Chart resolution now depends on ghcr.io reachability** rather than on a LAN host. A
  ghcr.io outage stalls reconciles that need a chart → Accepted. Chart pulls are small
  and occur per reconcile rather than per request, the kubelet caches the placeholder
  image after first pull, and the alternative is the single-host dependency this change
  exists to remove.
- **Repositories with no source in this repository** (`hello-static`,
  `nextcloud-wrapper`, `vaultwarden-wrapper`) may still back a live template → The audit
  covers them by querying templates rather than by reading the registry's catalog; any
  that is live is migrated like the others or its product is retired deliberately.
- **A change in flight that publishes a chart to the old location** would land an
  artifact somewhere this change is retiring → Any open change that packages a chart is
  rebased onto the new publishing path before it lands.

## Migration Plan

1. Add `products/custom/placeholder/VERSION`, the `--placeholder` target, and
   `scripts/publish-charts.sh`; wire both into CI's `publish-images` job.
2. Publish the placeholder image and all nine charts; set each new package to public and
   verify an anonymous pull of each.
3. Per product, in dependency order (`custom` last, since it also carries the placeholder
   reference): update the catalog file or author a new template version, roll out, move
   that product's deployments to the new template version, verify the release is healthy.
4. Audit: no template row and no live deployment names the internal registry.
5. Remove `--insecure-skip-tls-verify` from the reconciler's Helm path and from the
   product READMEs; update each README's publish section to the new commands.
6. Delete the `helm/*` and `caelus/*` repositories from the internal registry.

**Rollback:** before step 6, per product, point the deployments back at the previous
template version — the old chart is still published and still resolves. After step 6 the
rollback is to re-publish the affected chart to the internal registry, which is why step 6
is last and gated on step 4.

## Open Questions

- Do `hello-static`, `nextcloud-wrapper` or `vaultwarden-wrapper` still back a live
  template? Answered by the step 4 audit during implementation; it changes which charts
  step 3 covers, not the approach or the specs.
