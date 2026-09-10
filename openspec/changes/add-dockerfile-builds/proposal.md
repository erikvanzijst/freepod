## Why

The builder ignores a project's Dockerfile completely. Railpack has no Dockerfile
provider — its providers are `cpp deno dotnet elixir gleam golang java node php procfile
python ruby rust shell staticfile` — so a project that ships one is rebuilt from
Railpack's own detection with no warning, discarding everything the author encoded:
build arguments, system packages, multi-stage layout, a pinned base image. The
deployment then behaves in ways its author cannot explain from their own repository.

The failure is quiet and expensive. A project whose `package.json` start script is a dev
server deploys green and serves nothing; a Jekyll site fails for want of a start command
Railpack cannot infer. Both build correctly from the Dockerfile their authors already
wrote. Honouring it removes a whole class of "why did the platform do that" support
questions, and costs one branch in the builder: BuildKit interprets Dockerfiles through
a frontend the build pod's own daemon already knows how to run.

## What Changes

- The builder inspects the extracted project for a root `Dockerfile`. When one is
  present it builds that Dockerfile through BuildKit's Dockerfile frontend; when absent
  nothing changes and Railpack detection runs exactly as today.
- **BREAKING**: a deployment whose repository contains a root `Dockerfile` switches
  builder on its next deploy. Its Railpack configuration — including `railpack.json`
  build variables and a `Procfile` — stops taking effect, because those are Railpack's
  inputs and no longer read. A project relying on them must move that configuration into
  its Dockerfile.
- The chosen builder is named in the first line of the build output, so the log answers
  "why did it build that way" without anyone reading platform source.
- After the image is pushed, the builder reads its config back from the registry and
  warns — never fails — when the platform's port is not among the image's exposed ports,
  or when the image declares neither `CMD` nor `ENTRYPOINT`. Both are the shapes that
  deploy green and serve nothing.
- No fallback: a root Dockerfile that fails to build fails the build. Silently retrying
  with Railpack would reproduce the confusion this change exists to end.
- No build arguments and no build-time secrets in this version. A Dockerfile is built
  with its own `ARG` defaults.
- The component that interprets a Dockerfile is the platform's choice, not the project's.
  A `# syntax=` directive is overridden by a frontend the platform pins by digest, so a
  tenant cannot select the code that drives the build daemon.

Deliberately unchanged: the `$PORT` contract (the chart keeps dictating the container
port and the image must bind it), the per-owner layer cache and its repository, the
image output and tagging, the termination-message contract, the Job's resources,
deadline, namespace and network policy, and the absence of BuildKit entitlements — so
`RUN --security=insecure` and `network=host` keep failing with BuildKit's own error.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `build-execution`: stack detection becomes conditional on the project not carrying a
  root Dockerfile; a Dockerfile-built image becomes a supported outcome; the build
  output names the builder that ran and reports post-push contract warnings.

## Impact

- `products/custom/builder/build.py`: builder selection, the Dockerfile invocation and
  its pinned frontend, the post-push image-config check. Its README gains the precedence
  rule, the accepted risks, and the unchanged `$PORT` contract.
- `api/tests/test_builder_script.py`: coverage for selection, the second frontend's
  arguments, and the warnings.
- `cli/src/freepod/assets/SKILL.md` and `cli/src/freepod/__init__.py`: the packaged
  agent skill must state that a root Dockerfile takes over, since it currently reads as
  though Dockerfiles are merely unnecessary. Shipping it is a CLI release.
- `products/custom/builder/VERSION` and `tf/app/variables.tf`: a builder image release
  and the `builder_image` repoint, per the publish flow.
- Accepted operational risk, documented rather than mitigated here: Dockerfile builds
  pull base images from wherever the Dockerfile names them, including Docker Hub, which
  is unauthenticated, rate-limited and not mirrored by `registry.home`. A pull-through
  mirror is separate work.
- The Dockerfile frontend is pinned by digest and mirrored, the way the Railpack frontend
  already is, and `scripts/mirror-railpack-images.sh` gains it. A tenant `# syntax=`
  directive would otherwise let a project choose the code that drives the build daemon,
  which is a wider capability than running a build step: a frontend emits arbitrary LLB,
  names its own cache imports, and sits on the daemon's image-resolution path.
- No database migration, no API field, no chart change, no reconciler change.
