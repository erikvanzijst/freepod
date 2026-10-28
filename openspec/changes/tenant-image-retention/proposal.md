## Why

Every successful build leaves an image in its owner's registry repository, anchored by a
tag named after the build, and nothing ever removes the tag. Garbage collection only
reclaims what no tag reaches, so every image a deployment ever ran stays on disk
indefinitely. A deployment that ships many times a day accumulates hundreds of superseded
images it will never run again, and `local-path` enforces no quota to bound them.
The registry's own design deferred exactly this — "collection now, retention later" —
because deciding which images are still live is database knowledge.

## What Changes

- **A retention rule derived from the release ledger.** An owner's image is retained while
  it appears in the user values of a live deployment's desired release, its applied
  release, or the releases carrying its two most recent earlier images; or while the build
  that produced it is in flight or finished recently. Deleted deployments retain nothing.
  Retention is computed, never stored: no build or release gains an "expired" field.
- **A daily prune untags everything outside the rule** shortly before the registry's
  nightly garbage collection, which then reclaims the storage. The prune decides per tag
  by the digest it points to, so two builds that produced the same image are never
  confused, and images copied in without a build row are judged the same way.
- **A deployment write may only reference retained images.** Naming a build whose image is
  no longer retained, or submitting such an image among the user values, is rejected at
  the write with a clear error, instead of producing a release whose image cannot be
  pulled. **BREAKING** for API clients that redeploy arbitrarily old builds by id; the
  `freepod` CLI has no such path.
- **A new registry capability grants deletion**, to the prune alone: read and delete on
  exact image repositories, short-lived, never push, never the catalog. Builds and
  operator tooling still cannot delete.
- **A preview.** The prune can be run as a dry run that reports, per owner, which tags it
  would remove and how much storage they reach, without removing anything.

## Capabilities

### New Capabilities

- `tenant-image-retention`: which tenant images the platform keeps, how the rest are
  released to garbage collection, and how a deployment write is kept from referencing an
  image that is gone.

### Modified Capabilities

- `tenant-image-registry`: "Storage is reclaimable" — collection must spare every
  *retained* image, and an image's anchoring tag is removed once retention releases it.
- `registry-authorization`: adds the prune's deletion capability alongside the build's and
  the operator's, which still never delete.
- `deployment-release-ledger`: "A named build must belong to the deployment" — belonging
  is no longer the only condition; the named build's image must also be retained.

## Impact

- **API**: deployment create/update validation (`app/services/deployments.py`); a new
  retention module computing the retained set from the ledger; a new `caelus` command for
  the prune and its dry run; a delete-capable token in `app/services/registry_tokens.py`.
- **Infrastructure**: `tf/app` gains a daily CronJob running the prune with the registry
  signing key, scheduled ahead of the registry's restart-and-collect CronJob.
- **Clients**: a redeploy naming a build outside the window gets a 422 telling the caller to
  rebuild. The CLI's `--no-build` redeploys the applied image, which is always retained.
- **Storage**: superseded images stop accumulating; most of a busy owner's repository is
  reclaimed on the first night.
