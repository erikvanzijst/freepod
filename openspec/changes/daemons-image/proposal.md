## Why

Each Go daemon ships as its own image today (`app-auth`, `ssh-resolver`), so every new
daemon brings its own Dockerfile, its own `build-images.sh` branch, its own CI test job,
its own publish step, and its own GHCR package. The last is what has kept CI from
publishing them: a package first pushed by hand is never granted to the repo's Actions,
so CI has never pushed a versioned image. Object storage metering is about to add a
third daemon, a Garage bucket exporter, which is written in Go because a Python worker
on the API image costs 120–220 MiB per environment and a Go daemon costs 5–12 MiB.
Consolidating first means the exporter, and every daemon after it, only adds a binary.

## What Changes

- One image, `ghcr.io/erikvanzijst/freepod/daemons`, holds every platform Go daemon as
  a static binary on `scratch`. It has no entrypoint: each consumer names the binary it
  runs.
- The image keeps the existing daemons' release model: one immutable version, declared
  in the repository, never re-pushed. Each consumer pins its own version of the image,
  so `app-auth` and the SSH resolver still move only when Terraform names a new
  version for them, not when another daemon releases.
- The daemons move under `daemons/`: `app-auth/` → `daemons/app-auth/`, `ssh-auth/` →
  `daemons/ssh-auth/`. Each stays its own Go module with its module path unchanged. A
  `go.work` lets tooling see them together.
- One Dockerfile builds every daemon. `build-images.sh` gains `--daemons`, which
  replaces `--app-auth` and `--ssh-resolver`.
- One CI job vets and tests every daemon module, replacing `app-auth-test` and
  `ssh-auth-test`. One publish step pushes `daemons` when its version is new. CI makes
  the first push of the package, so the repo's Actions own it from the start.
- Terraform repoints `app-auth` and the SSH resolver at the first `daemons` version,
  which runs the same code they run today. The old `app-auth` and `ssh-resolver`
  packages stay published for rollback and receive no new versions.
- Paths that name the old directories move with them: tests that reach into sibling
  directories, READMEs, `AGENTS.md`, CI, the dev container. The HMAC domain string
  `"app-auth/"` in `seal.go` is not a path and does not change.

## Capabilities

### New Capabilities
- `daemons-image`: The shared image for the platform's Go daemons: what it contains,
  how it is versioned and published, how consumers select and pin it, and where its
  daemons live in the repository.

### Modified Capabilities
None. The verifier, broker and resolver behave exactly as before. Only how they are
built and shipped changes, and no existing spec covers that.

## Impact

- **Code moves:** `app-auth/` and `ssh-auth/` to `daemons/`. Relative paths in
  `daemons/ssh-auth/convention_test.go`, `daemons/ssh-auth/role_test.go`,
  `daemons/app-auth/store_test.go` and `api/tests/test_custom_chart.py` change.
- **Build:** new `daemons/Dockerfile`, `daemons/VERSION`, `daemons/.dockerignore`;
  `scripts/build-images.sh`; the two per-daemon Dockerfiles and VERSION files are
  removed.
- **CI:** `.github/workflows/ci.yml` (test jobs, publish step).
- **Terraform:** `tf/app/variables.tf` image defaults; `tf/app/app-auth/main.tf` and
  `tf/app/sshpiper/main.tf` set `command`. The resolver's listen address, an image
  `ENV` today, is already set by Terraform.
- **Docs:** `AGENTS.md`, both daemon READMEs, `tf/app/README.md`, links in
  `products/_lib/ssh-sidecar-*` READMEs and templates.
- **Registry:** a new GHCR package `daemons`, created by CI.
- **Rollout:** both environments re-pull their auth-path daemons once, onto the same
  code, through `terraform apply`. `scripts/rollout.sh` is unaffected.
- **Downstream:** the object storage metering change adds `daemons/bucket-exporter/`
  to this image.
