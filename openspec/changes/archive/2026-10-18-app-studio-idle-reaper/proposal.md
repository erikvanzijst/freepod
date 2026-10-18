# Proposal

## Why

An App Studio keeps everything the agent started running after the owner
leaves: dev servers (more than one, when the agent starts an app other than
through `dev-app`), PostgreSQL, Garage, and one `playwright-mcp` per app opencode
has opened, with a headless Chrome behind it for up to an hour after the agent's
last browser call. Three live studios held 0.7, 1.4 and 1.9 GB each, most of it
for nobody, on the tenant node every studio shares.

## What Changes

- **The studio suspends when nobody uses it.** After 30 minutes with no browser
  connected to opencode and no agent activity, the studio stops every process
  the agent left running in the background (dev servers, PostgreSQL, Garage,
  anything else it backgrounded) and the agent's Playwright MCP servers and
  browsers. opencode itself, its sessions and its terminals stay.
- **The preview comes back on its own.** When a browser connects to a
  suspended studio, the agent's browser tools return and the app that was in
  the preview is started again, with its database and bucket.
- **The agent's browser closes sooner.** Playwright MCP closes its headless
  browser after 10 minutes without a browser tool call instead of an hour; the
  next call relaunches it.
- **The agent knows servers may have stopped.** Its instructions say the dev
  server, database and S3 may have been stopped while the studio was idle, and
  to start them again rather than assume they run.
- Out of scope: stopping opencode itself or scaling the studio to zero, which
  needs a way to wake the pod on the next request.

## Capabilities

### New Capabilities
- `app-studio-idle`: when an App Studio counts as idle, what it stops when it
  is, what it brings back when the owner returns, and how long the agent's
  browser lives between uses.

### Modified Capabilities

None. The preview's one-app-at-a-time rule in `app-studio-projects` stands;
the idle capability only stops and restarts that app.

## Impact

- `products/appstudio/image/`: new `bin/appstudio-reaper` (Python, from the
  prototype in `var/appstudio-reaper.py`) and its `COPY` in the Dockerfile;
  `appstudio-start` starts it; `opencode.json` gains Playwright MCP's
  `--idle-timeout`; `AGENTS.md`; a new image version.
- `products/appstudio/chart/`: the new image and a chart version bump; the
  catalog entry `products/catalog/appstudio/appstudio.yaml` follows.
- `products/appstudio/README.md` and the product's docs page
  (`ui/docs/apps/products/appstudio.mdx`).
- Coupling: the reaper relies on opencode 1.19's `/global/event` stream,
  `GET /session/status` and `POST /mcp/<name>/disconnect` and `connect`, and on
  the web UI holding `/global/event` open while a tab is open.
