# daemons — the platform's Go daemons

Every Go daemon the platform runs, one directory and one Go module each, shipped
together in one image, `ghcr.io/erikvanzijst/freepod/daemons`, as `/<directory>`
on `scratch`. The image has no entrypoint: each consumer names its binary as the
container `command`, and pins its own exact version in `tf/app`.

- [`app-auth/`](app-auth/README.md): "Sign in with Freepod", `app_auth_image`
- [`ssh-auth/`](ssh-auth/README.md): the SSH auth resolver, `ssh_resolver_image`

Spec: [daemons-image](../openspec/specs/daemons-image/spec.md)

## Adding a daemon

Add a directory with its own `go.mod` and a `main` package at its root, and add
it to `go.work`. The Dockerfile and CI pick it up from there. Add its built
binary to `.dockerignore`.

## Testing

Each module builds and tests against its own `go.mod`; `go.work` is for editors.

```sh
cd daemons/<name> && GOWORK=off go vet ./... && GOWORK=off go test ./...
```

## Releasing

Bump `VERSION`. CI publishes `daemons:<VERSION>` on merge to master
(`scripts/build-images.sh --daemons --skip-if-published`); a published version
is never re-pushed. It reaches a daemon only when that daemon's image variable
in `tf/app/variables.tf` names it and is applied.
