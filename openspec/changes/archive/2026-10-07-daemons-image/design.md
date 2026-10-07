## Context

See `proposal.md` for the motivation and `specs/daemons-image/spec.md` for the
requirements. Facts that shape the approach:

- **Two daemons, built the same way twice.** `app-auth/Dockerfile` and
  `ssh-auth/Dockerfile` are near copies: `golang:1.25-bookworm`, `CGO_ENABLED=0 go
  build -trimpath -ldflags="-s -w"`, a `scratch` final stage with CA certificates,
  `USER 65534:65534`, one binary at the root. Each has its own `VERSION`, its own
  `build-images.sh` branch, its own CI test job and its own `--skip-if-published`
  publish step.
- **Both are pinned per consumer, on purpose.** `tf/app/variables.tf` pins
  `app_auth_image` and `ssh_resolver_image` to exact versions so the auth paths never
  roll because the API rolled. That property is kept (spec: *Each consumer pins its own
  exact version*).
- **CI has never published a versioned image.** Every `--skip-if-published` step has
  only ever found its version already pushed by hand. The one time CI really tried
  (builder 0.4.0), GHCR refused with `write_package`: a package first pushed with a
  personal token is not granted to the repository's Actions. GitHub's documentation
  says a package created by a workflow "inherits the visibility and permissions model
  of the repository where the workflow is run".
- **Both modules are self-contained.** Neither imports the other or anything else in
  the repository. Only tests reach outside their directory:
  `ssh-auth/convention_test.go` renders `../products/*/chart`, `ssh-auth/role_test.go`
  and `app-auth/store_test.go` read `../tf/app/caelus/*-bootstrap.sql`, and
  `api/tests/test_custom_chart.py` reads `app-auth/request.go`.
- **Terraform already sets everything the resolver's image `ENV` sets.**
  `CAELUS_SSH_RESOLVER_LISTEN` is set in `tf/app/sshpiper/main.tf`, and the readiness
  probe already runs `/ssh-auth -healthcheck` by absolute path.

## Goals / Non-Goals

**Goals:**
- Adding a daemon is adding a directory under `daemons/`: no Dockerfile, no script
  branch, no CI job, no registry package.
- The first `daemons` version runs exactly the code the current `app-auth` and
  `ssh-resolver` images run.

**Non-Goals:**
- Sharing Go code between daemons. Each stays its own module. Merging them into one
  module with `cmd/<daemon>` is the natural next step once two daemons share a
  package, and nothing here prevents it.
- Fixing CI's push rights on the other versioned packages (`builder`, `ssh-sidecar`,
  `custom-placeholder`). Those are separate packages with their own settings page.
- Bringing the Go daemons under `scripts/rollout.sh` or a moving tag.

## Decisions

### D1: One image, one version, pinned per consumer

`daemons/VERSION` names the image's version; `build-images.sh --daemons` builds
`ghcr.io/erikvanzijst/freepod/daemons:<version>` and refuses an existing tag, or skips
it under `--skip-if-published`, exactly as `--app-auth` does today.

Terraform keeps one variable per consumer (`app_auth_image`, `ssh_resolver_image`, and
later `bucket_exporter_image`), each naming a full reference to some version of
`daemons`. They may name different versions. Moving one variable is how a daemon
upgrades, and the only way.

*Alternative considered:* a version per daemon inside one image, i.e. tags like
`daemons:app-auth-0.3.0`. Rejected. It re-creates per-daemon release bookkeeping inside
one package, and a tag would still contain every other daemon's binary at whatever
state it was in, so the tag's name would describe one binary out of several.

*Alternative considered:* a moving tag rolled by `rollout.sh`, like the API image.
Rejected for the auth-path reasons the current pins exist for. A daemon that wants to
roll with the API can be repointed in the same apply.

**Consequence:** a new version may carry other daemons' unrelated changes. That's
harmless, because only the pinned daemon's binary runs from it. When a daemon is later
repointed to that version, its own diff since its previous pin is what gets reviewed.

### D2: No entrypoint; binaries named after their directories

The final stage sets neither `ENTRYPOINT` nor `CMD`. Every consumer sets `command`.
`tf/app/app-auth/main.tf` gains `command = ["/app-auth"]`, and `tf/app/sshpiper/main.tf`
gains `command = ["/ssh-auth"]`. That name matches the existing probe, so the binary
keeps its current name even though its package was called `ssh-resolver`.

A container that names no command fails to start (kubelet: `no command specified`).
That's the spec's *No command* scenario, and it beats silently running whichever daemon
a default picked.

The resolver Dockerfile's `ENV CAELUS_SSH_RESOLVER_LISTEN="127.0.0.1:50051"` is
dropped: Terraform already sets it, and an image shared by several daemons shouldn't
carry one daemon's configuration.

### D3: `daemons/<name>/` modules, built in a loop, with `GOWORK=off`

```
daemons/
  Dockerfile      builds every */go.mod into /<dir>
  VERSION
  .dockerignore   *_test.go, .tools/, built binaries
  go.work         editors and gopls only
  app-auth/       module github.com/erikvanzijst/caelus/app-auth (unchanged)
  ssh-auth/       module github.com/erikvanzijst/caelus/ssh-auth (unchanged)
```

- **Module paths stay unchanged.** A Go module path doesn't have to match its
  directory, and the repository is already `freepod` while the paths say `caelus`.
  Changing them would mean rewriting every import and regenerating
  `ssh-auth/internal/libplugin`, whose stubs embed the path. `proto_test.go` compares
  those stubs byte for byte, so a path change would ripple into the proto toolchain for
  no benefit.
- **The Dockerfile iterates over `*/go.mod`.** It downloads each module's
  dependencies in a cacheable layer, then runs `go build` once per directory into
  `/<dir>`. A daemon's `main` package is its directory root, as both are today. Build
  context is `daemons/` alone, which keeps the self-contained property the resolver
  Dockerfile's comment insists on.
- **`go.work` is for editors only.** In workspace mode Go resolves one dependency
  graph across all workspace modules, so `app-auth` could build with a newer library
  than its own `go.sum` pins just because `ssh-auth` requires it. Builds and CI
  therefore set `GOWORK=off`, and each module builds and tests against its own
  `go.mod`, exactly as today. `go.work` exists so gopls and `go` commands run from
  `daemons/` in the dev container see all modules.

*Alternative considered:* no `go.work`. Workable, but gopls then needs one VS Code
workspace folder per module, and the dev container opens the repository root.

### D4: One CI job loops over the modules

`daemons-test` replaces `app-auth-test` and `ssh-auth-test`. It runs in the dev
container as they do, because `ssh-auth`'s role test needs the migrated test database
that `post-create.sh` provisions. It runs `go vet ./...` and `go test ./...` in each
`daemons/*/` with `GOWORK=off`, and fails on the first failure. `publish-images`
depends on it.

A new daemon is picked up by the loop with no workflow edit (spec: *A new daemon is
checked*).

### D5: The first version is pushed by hand; CI publishes every later one

`daemons:0.1.0` is pushed by hand with `build-images.sh --daemons` before merge, so
dev can be repointed and checked ahead of it. The package is then made public, as the
cluster pulls platform images anonymously, and the repository's Actions are granted
write access in the package settings. From then on the CI step
`build-images.sh --daemons --skip-if-published` publishes each new version and skips
`0.1.0` as already published.

*Alternative considered:* let CI make the first push, so the package belongs to the
repository's Actions from the start. Rejected for this release: it would have
delayed checking the image on dev until after merge, and granting write access by
hand is a one-time step.

### D6: Paths that move, and one string that must not

Moved with the directories: the test fixtures' relative paths gain a `../`; the API
test's `app-auth/request.go` becomes `daemons/app-auth/request.go`; and links and
mentions in `AGENTS.md`, the daemon READMEs, `tf/app/README.md`,
`products/_lib/ssh-sidecar-chart/{README.md,templates/_shared.tpl}`,
`products/_lib/ssh-sidecar-image/{README.md,entrypoint.sh}`,
`products/custom/chart/templates/_helpers.tpl`, `cli/src/freepod/keys.py` (a comment),
`.devcontainer/Dockerfile` and `.devcontainer/post-create.sh` (comments).

`cli/src/freepod/keys.py` is under `cli/`, and every change there bumps
`freepod.__version__`. For a comment-only edit that cost isn't worth it, so that
comment keeps the old path and is fixed in the next real `cli/` change. Listed so it
isn't mistaken for an oversight.

Not moved: `mac.Write([]byte("app-auth/" + purpose))` in `seal.go`. It's an HMAC domain
separation string, not a path. Changing it would invalidate every sealed value in
flight.

Archived design documents keep their old paths. They're dated and immutable.

## Risks / Trade-offs

- **[One image carries every daemon]** A vulnerability scan of `daemons:N` reports
  findings in binaries a given consumer never runs. → Accepted. The binaries are static
  and run nothing they aren't told to, and a finding is fixed once for all daemons.
- **[Shared base, shared Go toolchain]** Bumping the Go version rebuilds every daemon
  in the next version. → That's per-version, not per-deployment: each daemon still
  moves only when its pin does, and gets reviewed then.
- **[CI can't push later versions]** if the package's Actions write access is missing.
  → D5 grants it once, at the first push; the publish step fails loudly otherwise.
- **[Auth paths restart once]** Repointing changes the image reference, so `app-auth`
  and the SSH edge pod restart on apply. → Same binaries, same configuration. Apply
  dev first. The SSH edge restart drops open sessions, which is already true for any
  resolver upgrade.

## Migration Plan

1. Move the directories, add the `daemons/` build files, update tests, CI, scripts and
   docs. Remove `app-auth/{Dockerfile,VERSION,.dockerignore}` and
   `ssh-auth/{Dockerfile,VERSION}`. Set `daemons/VERSION` to `0.1.0`.
2. Push `daemons:0.1.0` by hand, make the package public and grant the repository's
   Actions write access (D5). Confirm with
   `docker buildx imagetools inspect ghcr.io/erikvanzijst/freepod/daemons:0.1.0`.
3. Point `app_auth_image` and `ssh_resolver_image` at `daemons:0.1.0` and add the
   `command`s. `terraform apply` on the `default` (dev) workspace, check login and SSH on dev, then
   on `prod`.
4. Verify: `app-auth` pods ready and a sign-in works; the SSH edge pod ready
   (`/ssh-auth -healthcheck`) and an SFTP connection authenticates.

**Rollback:** repoint either variable at its previous dedicated image (`app-auth:0.2.0`,
`ssh-resolver:0.1.3`), which stays published, and remove the `command`. Those images
have an entrypoint, but an explicit `command` naming the same binary also works, so
removing it is optional.
