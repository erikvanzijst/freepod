# Tasks

## 1. Image: the reaper (D1–D5)

- [x] 1.1 Add `image/bin/appstudio-reaper` from `var/appstudio-reaper.py` (with the `wait()` thread on resume), executable, and add it to the Dockerfile's `COPY bin/appstudio-start …` line. Verify `appstudio-reaper plan` in the built image prints JSON with `groups`, `mcp_dirs` and `preview_dir`.
- [x] 1.2 Start it from `appstudio-start` just before `exec opencode`: `(while :; do appstudio-reaper || true; sleep 10; done) 2>&1 | tee -a /tmp/appstudio-reaper.log &`. Verify in the built image that `watching; idle after 1800s` appears in both `/tmp/appstudio-reaper.log` and `docker logs`, and that killing the reaper brings a new one within 10 s, shown in both.
- [x] 1.3 Rework the reaper to the revised D3–D5: check for a browser every 5 s; reconnect the event stream after 1 s; before suspending, `GET /session/status?directory=` for each `playwright-mcp` directory and cancel on any non-idle session; `POST /mcp/playwright/disconnect` instead of `/instance/dispose`; keep the preview and MCP directories in `/tmp/appstudio-reaper.state`, read it on start, and on resume `POST /mcp/playwright/connect` for each before starting `dev-app`. Verify `appstudio-reaper plan` still prints the plan and the image builds.
- [x] 1.4 Verify the browser and agent signals in running containers of the built image, with `APPSTUDIO_IDLE_AFTER=60`: a `curl -N localhost:4096/global/event` alone does not keep it from suspending; a connection to `:4096` from another container does, until it closes; a prompt sent before the reaper's first connection, whose agent runs a silent `sleep 150`, is not suspended until after the turn ends, and the `sleep` runs to completion.
- [x] 1.5 Verify suspend and resume in a container with `APPSTUDIO_IDLE_AFTER=60`: with `dev-app` running in one app, a hand-started `npm start` in another, PostgreSQL, Garage, an MCP opened through `GET /mcp?directory=…` with its Chrome running, and a terminal opened through `POST /pty` holding a `nohup sleep`, a suspend leaves only tini, opencode, the reaper, `tee` and the terminal with its `sleep`, with no zombies and `/mcp` reporting `disabled`; killing the reaper while suspended and letting it restart does not lose the state; a new outside connection reconnects the MCP (`connected`, and a browser tool call works), restarts the preview app with its database rows and bucket objects intact, and leaves the reaper no `<defunct>` child.
- [x] 1.6 Add the reaper to `products/appstudio/README.md`: a row for it, where its log goes (container output and `/tmp/appstudio-reaper.log`) with the Loki query, the coupling to opencode's `/global/event`, `/session/status` and `/mcp/<name>/disconnect` and `connect`, and a link to the `app-studio-idle` spec. Verify the spec links resolve (the `app-studio-idle` link once the change is archived).

## 2. Image: browser timeout and agent instructions (D6)

- [x] 2.1 Add `--idle-timeout`, `600000` to the `playwright` command in `image/opencode.json`, and note it in the README's Playwright MCP row. Verify in a studio session that after a browser tool call Chrome exits about 10 minutes later and the next browser call succeeds.
- [x] 2.2 Add to `image/AGENTS.md`, under "The preview": the dev server, database and S3 may have been stopped while the studio was idle; run `dev-app`, `dev-postgres` or `dev-s3` again rather than assume they run. Verify in a session after a suspend that the agent restarts the database before using it.
- [x] 2.3 Bump `image/VERSION`, build and push the image (`--build-context freepod-cli=cli`). Verify the new tag pulls and was never pushed before.

## 3. Chart and catalog

- [x] 3.1 Point `image` in `chart/values.yaml` at the new version and bump `Chart.yaml`. Verify with `helm lint` and `uv run pytest tests/test_appstudio_chart.py` in `api/`.
- [x] 3.2 Point `products/catalog/appstudio/appstudio.yaml` at the new chart version. Verify with `caelus catalog lint --dir ../products/catalog`.
- [x] 3.3 Describe idle behavior in `ui/docs/apps/products/appstudio.mdx`: what stops after 30 minutes away, that the preview comes back on return and other apps do not, that programs in an open terminal keep running. Verify the docs site builds (`npm run build` in `ui/docs`).

## 4. Release

- [x] 4.1 Publish the chart (`./scripts/publish-charts.sh appstudio`) and move the dev studio to it. Verify on the dev studio: closing the tab for 30 minutes leaves only opencode in the container (`ps`) and memory drops accordingly (`memory.current`); reopening it brings the preview back; `{namespace=~"app-studio-.*", container="opencode"} |= "appstudio-reaper:"` in Loki returns the suspend and resume lines.
- [x] 4.2 Prod follows the catalog on merge and rollout. Verify on a prod studio after 30 minutes unused that `memory.current` is down to roughly opencode's own footprint.

## Workflow follow-up

- Archive the change and sync `app-studio-idle` into the main specs.
- Delete `var/appstudio-reaper.py` and `var/appstudio-browsers.sh` once the image ships the reaper.
