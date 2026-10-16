# appstudio

App Studio: [opencode](https://opencode.ai)'s web UI (`opencode web`) over a
persistent workspace, in an image with Python, Node, uv, the `freepod` CLI and
its `deploy-to-freepod` skill. Experimental; not in the catalog.

| Component | Object(s) |
|-----------|-----------|
| opencode  | StatefulSet `<release>-app` (one replica), Service `<release>-app` `:80` → `$STUDIO_PORT` (4096) |
| Storage   | PVC `workspace` → `/workspace`, PVC `opencode` → `/root/.local/share/opencode` (sessions, provider credentials) |
| SSH key   | Secret `<release>-ssh`: an ECDSA key generated on first install and kept across upgrades, installed as `~/.ssh/id_ecdsa` |
| SFTP      | The platform's SSH sidecar with a read-only volume root of the project directory (`projectDir`) only, and its Service `<release>-ssh`; the rest of the workspace (credentials, opencode's config) is not mounted |
| Preview   | Ingress `<release>-preview` at `preview-<first label>.<rest of the host>` → port 8080, for whatever the agent runs there; while nothing listens, the chrome's `preview-down.html` waits for it. Wildcard-certificate hosts only |
| Sign-in   | Middlewares `<release>-strip-identity` and `<release>-app-auth` ahead of everything on both Ingresses: Sign in with Freepod, the owner's account only. The template must set `auth.enabled: true` as a system value; the chart refuses to render otherwise |
| Ingress   | `<release>-ingress`, only once the reconciler injects a hostname. A fresh load of `/` redirects to the chrome at `/.appstudio/`, with the project, `platformUrl` and the preview URL in its query |
| Chrome    | Container `chrome` (nginx, `chromeImage`) serving `chart/files/` from ConfigMap `<release>-chrome`: a bar with a link back to Freepod and a Preview button over opencode in an iframe. The button lights up while `/.appstudio/probe`, a proxy to the preview port, gets an answer, and opens the preview in its own window. On a browser's first visit the chrome adds the project to opencode's project list and opens a session with an example prompt typed in. Page edits reach a running pod without restarting it |

`appstudio-start` (`image/bin/`) prepares the workspace on every start and runs
`opencode web` from the project:

| Path | |
|------|-|
| `/workspace/app` | The project opencode opens on: an empty git repository until the agent copies the starter in |
| `/opt/appstudio/template`, `/opt/appstudio/examples` | The starter app (`image/template/`) and a reference app built on it (`image/examples/`), read-only |
| `/workspace/trees` | opencode's worktrees, through a link from its data directory |
| `/workspace/.config` | `XDG_CONFIG_HOME`: opencode's user config and skills, git's config, the freepod CLI's credentials and keys |
| `/etc/opencode/opencode.json` | opencode's managed config, which the user's cannot override |
| `/opt/appstudio/AGENTS.md` | The agent's instructions (`image/AGENTS.md`), loaded through the managed config's `instructions` |
| Playwright MCP | `@playwright/mcp` with Chrome for Testing in `/opt/ms-playwright`, registered as `playwright` in the managed config (headless, in-memory profile); the chart gives `/dev/shm` 512 Mi |

For local development the image carries PostgreSQL 18 and Garage (Freepod's
S3), neither started. `eval "$(dev-postgres)"` and `eval "$(dev-s3)"` start one
if needed and export the variables Freepod injects into a deployed app. `dev-app` runs
the project's dev server in the background on the preview port with both.

Access: [app-studio-access](../../openspec/specs/app-studio-access/spec.md),
[app-auth-chart-contract](../../openspec/specs/app-auth-chart-contract/spec.md).

## Image

`image/`, versioned by `image/VERSION`, never re-pushed. The `freepod` CLI is
installed from the repository's `cli/`, so build from the repository root:

```bash
docker buildx build --platform linux/amd64 --push \
  --build-context freepod-cli=cli \
  -t ghcr.io/erikvanzijst/freepod/appstudio:$(cat products/appstudio/image/VERSION) \
  products/appstudio/image
```

Then point `image` in `chart/values.yaml` at it, bump the chart and publish it
with `./scripts/publish-charts.sh appstudio`.
