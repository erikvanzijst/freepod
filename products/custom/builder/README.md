# builder

The image that turns a tenant's uploaded project archive into a container
image. One instance runs per build, as a Kubernetes Job in that environment's
builds namespace (`caelus-builds` in prod, `caelus-builds-dev` in dev), and it
is the only place in the platform where **tenant-supplied code executes**: a
project's dependency install hooks and build commands run inside it.

Everything about its shape follows from that.

## What it does

```
presigned artifact URL
        │
        ▼
  stream + extract (filtered, bounded, never staged on disk)
        │
        ├── Dockerfile at the project root?  ──yes──►  dockerfile.v0, pinned frontend
        │                                                     │
        └── no ──►  railpack prepare  ──►  railpack-plan.json  │
                                                    │         │
                                                    ▼         ▼
                          ephemeral rootless buildkitd  ←──  buildctl build
        │
        ▼
  push {registry}/{user_id}:{build_id}   →   digest from --metadata-file
        │                     ▲
        │                     └── layer cache in/out: {registry}/cache/{scope}/{user_id}
        ▼
  read the pushed config back, warn if it cannot serve
        │
        ▼
  /dev/termination-log:  {"image": "{user_id}@{digest}"}
```

## Which builder runs

A regular file named `Dockerfile` at the **project root** hands the build to
that Dockerfile. Anything else is detected by Railpack, exactly as before. The
first line of every build's log says which of the two ran.

There is no opt-out and no fallback. A project that ships a Dockerfile has
already said how it wants to be built, and a Dockerfile that fails to build
fails the build rather than quietly falling back to detection — a project that
builds one way today and another tomorrow is indistinguishable from a platform
fault.

Consequences worth knowing before enabling anything:

- **Railpack configuration stops applying.** `railpack.json` and `Procfile` are
  input to a builder that did not run. A project passing build variables that
  way must move them into its Dockerfile, since build arguments are not passed
  through yet.
- **The `$PORT` contract does not move.** The chart still assigns the port and
  the image must bind `0.0.0.0:$PORT`. A Dockerfile that hardcodes a port
  builds fine and serves nothing, which is what the post-push warning is for.
- **Base images come from wherever the Dockerfile names them.** Only ghcr.io is
  mirrored; a Docker Hub base image is pulled unauthenticated, subject to that
  registry's rate limits, on the critical path of the build.
- **`# syntax=` directives are overridden**, see below.
- **No entitlements are granted**, so `RUN --security=insecure` and
  `network=host` fail with BuildKit's own error.

## The Dockerfile frontend is ours, not the project's

Every Dockerfile build passes `build-arg:BUILDKIT_SYNTAX` naming a
digest-pinned frontend, which overrides any `# syntax=` directive in the file.

This is a security boundary rather than a preference. Whatever interprets a
Dockerfile is a *client of the build daemon*, not a build step: it emits its
own LLB, names its own cache imports, and sits on the daemon's image-resolution
path. A `RUN` instruction has none of that reach, so "the tenant runs their own
code either way" is true and beside the point — the two run with materially
different authority.

The image is addressed at the internal registry (`DOCKERFILE_FRONTEND_REPO` and
`DOCKERFILE_FRONTEND_DIGEST` in `build.py`), copied there by
`scripts/mirror-railpack-images.sh`. Not through a `docker.io` mirror entry in
the daemon config: that would route *every* Docker Hub pull in every tenant
Dockerfile through the internal registry, and exactly one image needs to come
from it. Unlike the Railpack images there is no fall-through — a Dockerfile
build fails outright until the mirror holds it.

The cost is that the pinned frontend's syntax level is the one tenants get.
Newer features fail with BuildKit's own error, and the remedy is a pin bump.

The container holds **no database, Kubernetes, or long-lived registry
credential**. The only credential it receives is a presigned URL that grants
read on exactly one object and expires. It reports its result through the pod's
termination message, so it never needs write access to anything — a
`DATABASE_URL` here would be a Postgres connection handed to every tenant, no
subversion of this script required.

## Environment contract

The build worker sets all of these on the Job.

| Variable                     | Required | Meaning                                                                                                                    |
|------------------------------|----------|----------------------------------------------------------------------------------------------------------------------------|
| `CAELUS_ARTIFACT_URL`        | yes      | Presigned GET for the project archive. Expiring, single-object.                                                            |
| `CAELUS_USER_ID`             | yes      | The build's owner. Becomes the repository name, the frontend cache key, and the layer cache repository.                    |
| `CAELUS_BUILD_ID`            | yes      | The build's id. Becomes the anchor tag.                                                                                    |
| `CAELUS_REGISTRY`            | yes      | Registry host, e.g. `registry.home`. Must match `registry` in the chart's `values.yaml`.                                   |
| `CAELUS_CACHE_SCOPE`         | yes      | Environment discriminator for the layer cache repository. The worker sets it to the builds namespace.                      |
| `CAELUS_WORKDIR`             | no       | Working tree. Default `/home/user/work`; the Job mounts an emptyDir here.                                                  |
| `CAELUS_ARTIFACT_MAX_BYTES`  | no       | Ceiling on the *compressed* stream. The worker sets it from the API's upload cap (`artifact_max_bytes`); default 100 MiB.  |
| `CAELUS_EXTRACTED_MAX_BYTES` | no       | Ceiling on the *extracted* tree. Default 800 MiB. This is the bound that matters: a 741-byte archive can expand to 500 KB. |
| `CAELUS_ARCHIVE_MAX_ENTRIES` | no       | Archive entry ceiling. Default 100,000.                                                                                    |
| `CAELUS_TERMINATION_LOG`     | no       | Default `/dev/termination-log`.                                                                                            |

## The layer cache is per owner, and that is the whole design

BuildKit runs *inside* this pod and dies with it. Its state — content store,
snapshots, and the frontend's dependency-install mount caches — lives on an
emptyDir, so nothing local survives to the next build. Left alone, every build
re-downloads and re-extracts the ~225 MB Railpack builder base before doing any
work of its own: measured at roughly 26s of a 62s build, split about evenly
between transfer and decompression.

So the cache that survives has to be a remote one. Each build imports from and
exports to a registry cache at:

```
{CAELUS_REGISTRY}/cache/{CAELUS_CACHE_SCOPE}/{CAELUS_USER_ID}:latest
```

**One repository per owner per environment, never shared.** A build cache is an
execution result keyed by a hash the tenant controls, so a cache two tenants
can reach is not an optimization, it is a channel: poison an entry and the next
tenant's build executes it. The ref is built in `cache_ref()` from values the
platform supplies and nothing from inside the archive, which is what makes that
claim checkable. It pairs with `build-arg:cache-key`, which scopes the
frontend's own mount cache ids the same way.

`CAELUS_CACHE_SCOPE` — the builds namespace, so `caelus-builds` or
`caelus-builds-dev` — is why the owner alone is not enough. Dev and prod run
**separate databases behind one registry**, so their user id sequences are
independent and user 1 in dev is a different person from user 1 in prod. Under
the owner alone they would share a repository *and* a stable tag, reading and
overwriting each other. The image repositories (`{registry}/{user_id}`) carry
the same ambiguity and get away with it only because their tags are
unguessable build UUIDs — a cache under one moving tag has no such cover. The
variable is required rather than defaulted for the same reason: a missing scope
would silently collapse the two environments back together.

Some consequences worth knowing:

- **The first build for an owner has nothing to import.** BuildKit warns and
  proceeds; there is no repository to create beforehand and nothing to repair
  if one is deleted.
- **A failed export never fails a build.** The image is already pushed by the
  time the cache is written, so the export carries `ignore-error=true`: a full
  or briefly unreachable registry costs a build its cache, not its result.
  The flip side is that a *persistently* broken export is silent — if build
  times stop improving, look for `error: failed to solve: ... exporting cache`
  in the build log rather than assuming the cache is working.
- **`mode=max` is deliberate.** The expensive step is dependency installation,
  whose result never reaches the runtime image. `mode=min` records only the
  final image's layers and would leave that step re-running every time.
- **It costs registry disk**, on the registry host rather than the cluster
  node, and it grows per owner with every distinct dependency set. There is no
  eviction policy yet: `mode=max` under one moving tag means each export
  unreferences the previous one's blobs, so a registry garbage collection pass
  reclaims them, but nothing bounds a single owner's working set. Worth
  watching before the owner count grows.
- **Emptying `cache/{scope}/{user_id}` is always safe** — it forces the next
  build cold and nothing needs recreating.
- **The cache shares the registry with the images.** That is what lets a cache
  hit be mounted across repositories at push time instead of pulled down and
  sent back up.

## Untrusted input handling

The archive is tenant-supplied and is treated as hostile regardless of the
sandbox around it. Extraction runs through Python's `tarfile` **`data` filter**
— the standard library's purpose-built answer for untrusted archives — plus
explicit bounds applied *before* each member is written:

| Attack                                              | Outcome                                  |
|-----------------------------------------------------|------------------------------------------|
| `../escape.txt`, `../../escape.txt`                 | rejected                                 |
| absolute path `/tmp/escape.txt`                     | rejected                                 |
| symlink or hardlink pointing outside the tree       | rejected                                 |
| entry-count bomb                                    | rejected at `CAELUS_ARCHIVE_MAX_ENTRIES` |
| decompression bomb, single or spread across members | rejected at `CAELUS_EXTRACTED_MAX_BYTES` |

The absolute-path rejection is ours rather than the filter's: `data` *rewrites*
an absolute path to a relative one instead of refusing it, which is safe but
would surface much later as an unexplained "no project detected". The size and
entry bounds are checked before extracting each member, so the member that
would breach a limit is never written at all.

## Build output

What this container emits is plain text with no terminal control sequences.
Two of its lines are worth knowing: the first names the builder that ran, and
after the push the builder reads the image's config back from the registry and
warns — never fails — about the two shapes that deploy green and serve nothing.

An image whose declared ports exclude the platform's is warned about; declaring
*no* ports is not, because no Railpack-built image emits `EXPOSE` and a warning
that fires on nearly every build teaches people to skip the one that matters.
An image with neither an entrypoint nor a command is warned about too: it has
nothing to run and will exit immediately.

**Tenant build output is a different matter and is deliberately not
sanitized.** BuildKit runs the tenant's build steps in containers of its own,
with the environment coming from the build plan, so nothing set on this
container reaches them — a real build shows `dpkg` emitting bare CR progress
redraws (`Reading database ... 5%\r10%\r…`). A tenant can print arbitrary
bytes, and the platform stores them faithfully rather than rewriting them,
which is why the `build.log` column is `bytea`. Rendering is the reader's
choice; a client that wants a tidy transcript can collapse CR runs itself.

## Pulls from ghcr.io go through the internal registry

Before a build runs a line of the tenant's own code it pulls the Railpack
frontend, builder and runtime images. With BuildKit's state on an emptyDir none
of that is ever reused — measured on a 62s build, materializing the 225 MB
builder base alone took ~26s, split roughly evenly between transfer and
decompression.

The ephemeral daemon is therefore configured with the internal registry as a
**mirror for ghcr.io** (`buildkitd_config` in `build.py`, written at startup and
passed as `--config` through `BUILDKITD_FLAGS`). `scripts/mirror-railpack-images.sh`
copies the images in.

A mirror is a per-repository substitution, not a host alias: BuildKit asks the
mirror for the *same* path, so `ghcr.io/railwayapp/foo` is looked for at
`{registry}/railwayapp/foo`. That is where the script puts them.

## The pinned versions must move together

`railpack` (Dockerfile `ARG RAILPACK_VERSION`), the frontend image
(`FRONTEND_IMAGE` in `build.py`) and the mirror script's pins are a
**version-matched set**. The build plan `railpack prepare` emits is a contract
between the binary and the frontend, so bumping one without the other hands a
plan to a frontend that cannot read it; a mirror of the wrong release's images
is simply never consulted. Tests in `api/tests/test_builder_script.py` fail if
the script drifts from the other two.

Currently both are v0.36.4:

```
railpack                     0.36.4
ghcr.io/railwayapp/railpack-frontend@sha256:282e3d0e542c9299c9fc4f938c9a5c45f0666d954264deaea59d13281121a91a
```

The Dockerfile frontend is **not** part of that set — it understands no
railpack plan and moves on its own cadence — but it is pinned and mirror-checked
the same way, and the same test file fails if `build.py` and the mirror script
disagree about its digest.

To bump: pick the new railpack release, update `RAILPACK_VERSION` and
`RAILPACK_SHA256` from that release's `checksums.txt`, then resolve the
matching frontend digest and update `FRONTEND_IMAGE`:

```bash
TOKEN=$(curl -s "https://ghcr.io/token?scope=repository%3Arailwayapp%2Frailpack-frontend%3Apull" | jq -r .token)
curl -sI -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.oci.image.index.v1+json" \
  "https://ghcr.io/v2/railwayapp/railpack-frontend/manifests/v<NEW_VERSION>" |
  grep -i docker-content-digest
```

Pinning by digest here is about that coupling, not supply chain — a digest is
content-addressed, and the project already consumes public images by tag
elsewhere.

`MISE_TAG` in the mirror script is the third pin, and unlike the other two it
is chosen by Railpack rather than by us, so it is recorded nowhere else in this
repo. After a bump, run one build and read the images out of its log:

```bash
kubectl logs -n caelus-builds <build pod> | grep -o 'docker-image://[^ ]*' | sort -u
```

Then update `MISE_TAG` and re-run the mirror script. Until you do, builds fall
back to ghcr.io and are merely slow.

## Build and publish

**amd64 only.** The cluster node is amd64 and multi-arch is an explicit
non-goal, so the Dockerfile fails the build on any other architecture rather
than producing an image whose `railpack` binary cannot exec.

The image is published to ghcr.io alongside the platform's own images, on an
immutable version tag taken from `VERSION` in this directory. Bump that file,
then:

```bash
./scripts/build-images.sh --builder
```

An already-published version is refused rather than overwritten: a build Job
names this image by tag, so re-pushing one would change what executes tenant
code without any version having moved. CI runs the same command with
`--skip-if-published` on every merge, so a push lands exactly when `VERSION`
names a version GHCR does not already hold.

A first push creates the package at GHCR's default visibility, which is
private, and nothing configures an `imagePullSecret` — see
[`tf/app/README.md`](../../../tf/app/README.md).

Then point the platform to it through `builder_image` in Terraform, and mirror
the Railpack base images if this is a new registry or a new Railpack version:

```bash
./scripts/mirror-railpack-images.sh
```

## Node prerequisites

Node-level settings are required and **neither is captured by Terraform**;
a rebuilt node fails at two separate points with unrelated-looking errors.

1. `/etc/sysctl.d/99-buildkit-userns.conf` — `kernel.apparmor_restrict_unprivileged_userns=0`.
   Ubuntu 24.04 ships this at `1`, which transitions any unconfined process
   calling `userns_create` into a restrictive AppArmor profile that then denies
   `CAP_SYS_ADMIN` in the new namespace. Setting the pod to
   `appArmorProfile: Unconfined` does **not** help — the transition fires *from*
   the unconfined profile.

The Job additionally needs both `seccompProfile: Unconfined` and
`appArmorProfile: Unconfined` — these cover the *container* profile blocking
`mount`/`unshare`, which is a separate mechanism from the host sysctl above.
