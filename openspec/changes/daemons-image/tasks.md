## 1. Move the daemons

- [ ] 1.1 `git mv app-auth daemons/app-auth` and `git mv ssh-auth daemons/ssh-auth`; verify `git status` shows renames only and the module paths in both `go.mod` files are unchanged
- [ ] 1.2 Fix the tests' relative paths (`daemons/ssh-auth/convention_test.go`, `daemons/ssh-auth/role_test.go`, `daemons/app-auth/store_test.go`: one more `../`), and make sure `seal.go`'s `"app-auth/"` HMAC string is untouched; verify `GOWORK=off go vet ./... && GOWORK=off go test ./...` passes in each module
- [ ] 1.3 Point `api/tests/test_custom_chart.py` at `daemons/app-auth/request.go`; verify `uv run --no-sync pytest tests/test_custom_chart.py` passes
- [ ] 1.4 Add `daemons/go.work` using both modules; verify `go list ./...` from `daemons/` lists both modules' packages and `go.work.sum`, if created, is committed

## 2. The shared image

- [ ] 2.1 Add `daemons/Dockerfile` (D2, D3): download each `*/go.mod`'s dependencies in a cached layer, build every directory with `GOWORK=off CGO_ENABLED=0 go build -trimpath -ldflags="-s -w"` into `/<dir>`, `scratch` final stage with CA certificates, `USER 65534:65534`, no `ENTRYPOINT`/`CMD`. Add `daemons/.dockerignore` (`*_test.go`, `.tools/`, built binaries) and `daemons/VERSION` = `0.1.0`. Verify `docker build daemons/` succeeds, the image lists exactly `/app-auth` and `/ssh-auth` plus the certificates, and `docker run` with no command fails to start
- [ ] 2.2 Verify each binary still runs from the image: `docker run --rm <img> /ssh-auth -healthcheck` exits nonzero without a server (it doesn't crash on startup), and `/app-auth` starts and fails only on missing configuration
- [ ] 2.3 Remove `daemons/app-auth/{Dockerfile,VERSION,.dockerignore}` and `daemons/ssh-auth/{Dockerfile,VERSION}`; verify nothing in the repository still references them (`grep -rn` for `app-auth/VERSION`, `ssh-auth/VERSION`, `app-auth/Dockerfile`, `ssh-auth/Dockerfile` outside `openspec/changes/archive/`)

## 3. Build script and CI

- [ ] 3.1 Replace `--app-auth` and `--ssh-resolver` in `scripts/build-images.sh` with `--daemons`: tag from `daemons/VERSION`, refuse an existing tag, skip it under `--skip-if-published`; update usage, the header comment and the closing hint (repoint the per-consumer variables in `tf/app`). Verify `./scripts/build-images.sh --help` shows `--daemons` and neither old flag, and that `--daemons --skip-if-published` against a tag that exists reports "already published" and exits 0
- [ ] 3.2 Replace `app-auth-test` and `ssh-auth-test` in `.github/workflows/ci.yml` with one `daemons-test` job (D4) that loops over `daemons/*/` with `GOWORK=off go vet ./... && go test ./...`, stopping at the first failure; make `publish-images` depend on it and replace the two publish steps with `./scripts/build-images.sh --daemons --skip-if-published`. Verify the workflow parses (`actionlint`, if available, or a push to a branch) and the loop fails when a module's test is made to fail locally

## 4. Terraform

- [ ] 4.1 `tf/app/app-auth/main.tf`: `command = ["/app-auth"]`. `tf/app/sshpiper/main.tf`: `command = ["/ssh-auth"]` on the resolver container. Leave the image defaults in `tf/app/variables.tf` on the old images until 0.1.0 is published. Verify `terraform validate` in `tf/app/` and that a `terraform plan` on dev shows only the `command` additions on the two pods
- [ ] 4.2 After CI has published `daemons:0.1.0` (`docker buildx imagetools inspect ghcr.io/erikvanzijst/freepod/daemons:0.1.0`), set `app_auth_image` and `ssh_resolver_image` defaults to that reference and update their descriptions; verify `terraform plan` on dev shows only the two image changes

## 5. Docs

- [ ] 5.1 Update paths and links in `AGENTS.md`, `daemons/app-auth/README.md`, `daemons/ssh-auth/README.md`, `tf/app/README.md`, `products/_lib/ssh-sidecar-chart/{README.md,templates/_shared.tpl}`, `products/_lib/ssh-sidecar-image/{README.md,entrypoint.sh}`, `products/custom/chart/templates/_helpers.tpl`, `.devcontainer/Dockerfile` and `.devcontainer/post-create.sh` (comments). Leave `cli/src/freepod/keys.py` as is (D6). Add a terse `daemons/` entry to `AGENTS.md`'s architecture notes, linking the `daemons-image` spec and this design. Verify every relative link to `ssh-auth/` or `app-auth/` outside `openspec/changes/archive/` resolves
- [ ] 5.2 Re-render any product chart whose templates changed (comment-only changes to `_shared.tpl`/`_helpers.tpl`) and check the chart's version rules: if a template change would require a chart version bump, move those comments to the README instead. Verify `./scripts/publish-charts.sh` would publish nothing new for comment-only edits, or bump consistently

## 6. Roll out

- [ ] 6.1 Merge; confirm CI's `daemons-test` passed and its publish step created `daemons:0.1.0` (D5). If GHCR denies the first push, push by hand, grant the repository's Actions write access in the package settings, and record that in the PR
- [ ] 6.2 Apply task 4.2 to the `default` (dev) workspace: `app-auth` in `login-dev` is ready and a "Sign in with Freepod" login on a dev app works; the `sshpiper-dev` pod is ready and an SFTP connection to a dev deployment authenticates
- [ ] 6.3 Apply to `prod` and repeat 6.2's checks against prod
