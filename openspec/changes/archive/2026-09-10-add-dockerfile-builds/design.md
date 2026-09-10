## Context

See proposal.md — Why. What matters for the approach:

- `products/custom/builder/build.py` already runs a rootless BuildKit daemon per build
  and drives it with one `buildctl` invocation: `--frontend=gateway.v0` against the
  Railpack frontend image, pinned by digest, with the generated plan as its "dockerfile".
  Everything around that call — the presigned artifact download, extraction under three
  bomb guards, the per-owner registry cache, the image output, the `--metadata-file` the
  termination message is built from — is builder-agnostic already.
- BuildKit interprets Dockerfiles through a frontend. One implementation is compiled into
  the daemon, but a project's `# syntax=` directive replaces it, so which one runs is only
  the platform's choice if the platform pins it (D2, D3).
- The platform's runtime contract lives in the chart, not in the builder:
  `products/custom/chart/values.yaml` sets `containerPort: 8080` and the deployment
  injects it as `PORT`. Nothing in `api/app/` mentions the number.
- The build pod's NetworkPolicy already permits egress to the registry on 443 and 80,
  and to the public internet for dependency fetching.

## Goals / Non-Goals

**Goals:**

- One decision point in the builder, with everything on both sides of it shared.
- A tenant can read the build log and know which builder ran and why their image may not
  serve.
- No new privilege, credential, or entitlement reaches tenant build code, and nothing
  with more authority than a build step is selectable by the project.

**Non-Goals:**

- Changing the `$PORT` contract, or deriving the container port from the image.
- Build arguments and build-time secrets.
- Mirroring Docker Hub.
- Any database, API, chart or reconciler change.

## Decisions

### D1: Presence of a root Dockerfile decides, with no opt-out

The file's presence selects the builder. No `.freepod.json` field, no flag.

Alternatives considered. *Opt-in* (a Dockerfile is ignored unless configured) keeps every
existing deployment on its current builder, but makes the obvious case — "I have a
Dockerfile, use it" — require configuration, and leaves the feature invisible to anyone
who does not read the docs. *Opt-out* (a `builder` field pinning the choice) avoids the
redeploy surprise below, at the cost of a config surface in the CLI, the API and the
project file for a case we expect to be rare.

The cost is real and accepted: a deployment whose repository already contains a root
Dockerfile changes builder on its next deploy, without the tenant changing anything. The
mitigations are the log line (D8), the skill documentation, and the fact that a
Dockerfile is the build its author actually wrote. Every escape hatch remains available
to them — deleting or renaming the Dockerfile restores detection.

### D2: The Dockerfile frontend is pinned by the platform, mirrored, and referenced by digest

`--frontend=dockerfile.v0` selects BuildKit's Dockerfile frontend, and
`--opt build-arg:BUILDKIT_SYNTAX=<mirrored image>@sha256:<digest>` fixes which build of it
runs. The image is mirrored into the internal registry by
`scripts/mirror-railpack-images.sh`, alongside the Railpack images it already copies, and
named by digest so a mirror serving something else fails closed rather than silently.

The daemon's built-in Dockerfile implementation would need nothing pulled or pinned, but
it cannot be *guaranteed*: a project's `# syntax=` directive replaces it, and that is the
capability D3 refuses to hand out. Pinning is what makes the choice ours, so the pin is
not overhead — it is the mechanism.

Referencing the mirror copy directly, rather than adding a `docker.io` entry to the
daemon's mirror configuration, is deliberate. A mirror entry would route *every* Docker
Hub pull in every tenant Dockerfile through the internal registry, which widens the blast
radius of that registry's write access to the whole of Docker Hub. One digest-pinned
reference does not.

The cost is a hard dependency: if the frontend image is absent from the internal
registry, Dockerfile builds fail. That is a loud, immediate failure with an obvious
remedy (re-run the mirror script), and it is preferable to the quiet alternative of
falling back to whatever the project asked for.

### D3: A project cannot choose what interprets its Dockerfile

`# syntax=` directives are overridden, not honoured. Verified: a Dockerfile whose
directive names a non-existent frontend fails to resolve it normally, and builds cleanly
with `BUILDKIT_SYNTAX` set to a digest-pinned reference — the named frontend is never
fetched.

This reverses the position taken earlier in this change's discussion, on the strength of
one correction. A frontend is not a build step. It is a gRPC client of the build daemon:
it emits arbitrary build instructions rather than executing one, it names its own cache
imports, it reads every local context the client exposed, and it sits on the daemon's
image-resolution path. A `RUN` instruction has none of that reach. "Tenant code runs
either way" is true and beside the point — the two run with materially different
authority.

Today the practical difference is small, because the build session carries no
credentials. That is precisely the argument for pinning now: authenticating the internal
registry is desirable for unrelated reasons, and the day it happens the session grows
secrets that a tenant-selected component would be adjacent to. Fixing the ordering later
means re-litigating this under pressure.

Alternatives considered. *Honouring the directive* is what every other Docker toolchain
does and maximises compatibility with Dockerfiles in the wild; rejected on the authority
argument above. *Rejecting a Dockerfile that carries a directive* keeps the built-in
frontend and pulls nothing, but `# syntax=docker/dockerfile:1` is boilerplate in a large
share of real repositories, and refusing a Dockerfile the built-in frontend would have
compiled perfectly well is a bad trade for the tenant.

The residual cost is that the pinned frontend's syntax level is the one tenants get.
Features newer than the pin fail with BuildKit's own "unknown instruction" style error,
and the remedy is a pin bump — the same maintenance the Railpack frontend digest already
carries.

### D4: Cache flags are unchanged; only the cache-key build arg drops

`--import-cache` / `--export-cache` keep pointing at the same per-owner ref computed by
`cache_ref`, with `mode=max` and `ignore-error`. `--opt build-arg:cache-key` is dropped
because it namespaces the *Railpack frontend's* mount cache ids and means nothing to
`dockerfile.v0`.

Dropping it does not weaken isolation. A tenant Dockerfile's `RUN --mount=type=cache`
ids are tenant-chosen, but the daemon is created and destroyed with the build and its
state lives on an emptyDir that dies with the pod, so no local cache is ever shared
between builds. The only cache that survives is the registry one, whose ref is derived
entirely from platform values.

### D5: No fallback to detection

A root Dockerfile that fails to build fails the build. Falling back would mean a project
builds one way today and another way tomorrow depending on whether its Dockerfile
happened to compile — the same class of unexplainable behaviour this change removes.

### D6: The contract check reads the published image's config

After the push, the builder fetches the image manifest and config blob from the registry
by digest and inspects `ExposedPorts`, `Entrypoint` and `Cmd`.

The alternative, parsing `EXPOSE` out of the Dockerfile text, needs no network but is
wrong for the common case: ports inherited from a base image are invisible to it, and
multi-stage builds make "the final stage" a parsing problem. Reading what was actually
published is both simpler and correct.

The registry call skips TLS verification, for exactly the reason `registry.insecure=true`
is already passed to BuildKit: the internal registry presents a certificate for a name it
is not addressed by. It is the same host, over an egress path the NetworkPolicy already
allows, and a failure to inspect must not fail an otherwise good build.

### D7: The platform port is a constant in the builder

`build.py` carries the port as a constant whose comment names
`products/custom/chart/values.yaml` as the value it mirrors.

The alternative — a `CaelusSettings` field threaded into the Job's environment, and from
the same setting into the chart's `containerPort` — is the correct end state and removes
the second copy. It was rejected for this change because it reaches the reconciler and
the chart contract for the sake of a warning string, in a change that is otherwise
confined to one file. The drift is bounded: if the chart's port changes and the constant
does not, a warning becomes wrong, and nothing else breaks.

### D8: Provenance is the build log

The first line of build output names the builder. No column on the build row, no field
on the build API, no CLI display.

The alternative is queryable and survives log retention, at the cost of a migration and
two more specs. The question this answers — "why did my project build that way" — is
asked while looking at a build's log, which is where the answer now is.

### D9: No build arguments in this version

A Dockerfile is built with its own `ARG` defaults.

This is the sharpest edge of the change: a project that today passes build variables
through `railpack.json` loses them the moment the Dockerfile path takes over, because
those variables are Railpack's input. The affected project's migration is to bake the
value into its own Dockerfile, which is a one-line edit in a file it already owns.

Passing build arguments through is worth doing and is deliberately not bundled here: it
needs a decision about where the values come from (project file, deployment variables,
a new API field) and it is the same plumbing as build-time secrets, which carries its own
security design.

## Risks / Trade-offs

- **A live deployment silently changes builder on redeploy** → The build log names the
  builder from its first line; the packaged skill documents the precedence rule; the
  release note calls it out. Renaming the Dockerfile restores the previous behaviour.
- **Build variables in `railpack.json` stop applying to Dockerfile projects** → Documented
  in the skill and the builder README as the migration above. Detectable in one place: a
  project with both a Dockerfile and a `railpack.json` is exactly the shape at risk, and
  the builder's log line makes the switch visible on the first affected build.
- **Base images pull from Docker Hub, unmirrored and rate-limited** (100 anonymous pulls
  per 6 hours per IP; `registry.home` mirrors only ghcr.io, and a `registry:2` cannot both
  accept pushes and act as a pull-through cache) → Accepted for this version. Failures are
  per-build, self-resolving and confined to one tenant. A second registry instance in
  pull-through mode is follow-up work.
- **The pinned frontend caps the Dockerfile syntax tenants can use** → Failures name the
  instruction and are fixed by bumping the pin. Accepted as the price of D3; the pin sits
  next to the Railpack frontend digest so both are bumped in the same place.
- **The mirrored frontend image is a hard dependency of every Dockerfile build** → Absence
  fails builds loudly rather than silently falling back. The mirror script publishes it,
  and its own verification step should confirm the digest the builder expects.
- **Tenant Dockerfiles can produce very large images** → No new exposure: nothing caps
  image size for detected builds either. Registry disk is an existing operational concern.
- **The contract warnings are heuristics and can mislead** → They warn and never fail, and
  their wording says the image *may* not serve. The port warning fires only on a
  contradiction — declared ports that exclude the platform's — because declaring none is
  the norm: no Railpack-built image emits `EXPOSE`, so warning about absence would fire on
  nearly every build and devalue the warning that means something.

## Migration Plan

1. Land the builder change with its tests.
2. Bump `products/custom/builder/VERSION`, publish with `./scripts/build-images.sh
   --builder`, repoint `builder_image` in `tf/app/variables.tf`, and apply. Until the
   apply, every build keeps using the previous builder image and behaviour is unchanged.
3. Release the CLI for the packaged skill (`freepod.__version__` bump plus a `freepod-v*`
   tag); agents pick it up on their next `freepod skill install`.

Rollback is repointing `builder_image` at the previous version and applying: the
published images from either builder are ordinary images and deployments referencing them
by digest are unaffected.

## Open Questions

- Whether a Docker Hub pull-through mirror is worth standing up, and where it lives —
  answerable after we see how often Dockerfile builds actually hit rate limits.
- Whether build arguments arrive as a project-file field, as deployment variables scoped
  to build time, or as part of the build-time secrets design.
