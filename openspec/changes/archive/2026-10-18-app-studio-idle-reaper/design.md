# Design

## Context

The studio's `opencode` container runs `tini` → `appstudio-start`, which `exec`s
`opencode web` (1.19.0). Measured on three live studios (proposal.md - Why),
broken down by RSS:

| Process                         | RSS                                 | Lifetime today                                                                                 |
|---------------------------------|-------------------------------------|------------------------------------------------------------------------------------------------|
| `opencode web`                  | 0.5–0.8 GB                          | the pod's                                                                                      |
| dev server (`tsx watch` + Vite) | 0.1–0.45 GB each                    | forever; agents start more than one                                                            |
| headless Chrome                 | ~0.5–1 GB, shared pages overcounted | 1 h after the last browser tool call (Playwright MCP's default `--idle-timeout` when headless) |
| `playwright-mcp` (Node)         | 110–135 MB each                     | forever; opencode starts one per app directory it opens                                        |
| PostgreSQL / Garage             | ~100 MB / ~35 MB                    | forever                                                                                        |

Established on a live studio with opencode 1.19.0:

- The web UI holds `GET /global/event` (SSE) open while its tab is open,
  background tabs included. Traefik's access log shows these streams lasting
  as long as the tab (e.g. 110 min). Traefik reaches opencode over HTTP/1.1, so
  one tab can show as several established connections to `:4096`.
- `/proc/net/tcp` in the pod lists those connections with the Traefik pod as
  remote address; they disappear when the tab closes. The image's `awk` is
  mawk, without `{n}` regex intervals or `strtonum`.
- `/global/event` carries every directory's events, each tagged with
  `directory`, plus a `server.heartbeat` every ~10 s.
- `GET /session/status` is scoped to one directory (`?directory=`, default the
  server's working directory, `/workspace/apps/app`). It reports
  `{"<id>":{"type":"busy"}}` for the whole of a turn, including a tool call
  that emits no events. `GET /api/session/active` stays empty during a turn.
- An instance starts no MCP server until something needs one (`GET /mcp`, a
  session); a working session's directory always has its `playwright-mcp`.
- `POST /mcp/playwright/disconnect?directory=<dir>` stops that directory's
  `playwright-mcp` and leaves its status `disabled`; `POST …/connect` starts it
  again. `POST /instance/dispose` also stops it, but closes the instance's
  terminals and ends a running turn.
- Everything the agent backgrounds (`npm run dev` via `dev-app`'s `setsid`, a
  bare `npm start`, PostgreSQL, Garage) ends up with PPID 1, each in its own
  process group. opencode's own children (MCP servers, terminal shells) stay
  under opencode's PID. `kubectl exec` shells have PPID 0.

A prototype (`var/appstudio-reaper.py`) suspended and resumed a live studio as
specified, with the preview back within seconds of reopening the tab.

## Goals / Non-Goals

**Goals:**
- One self-contained process in the existing container; no chart topology
  change, no change to the chrome page.
- Only opencode's public HTTP API and `/proc`; no patches to opencode.

**Non-Goals:**
- Reducing opencode's own footprint, or restarting it to reclaim memory it
  grew.
- Restoring apps other than the preview, or the agent's browser state.
- Configurable thresholds per deployment.

## Decisions

### D1. `appstudio-reaper` in the opencode container, Python

A Python script (the image has 3.11) in `image/bin/`, started by
`appstudio-start` just before `exec opencode`, wrapped in a restart loop
(`while :; do appstudio-reaper || true; sleep 10; done`; `|| true` because `appstudio-start` runs with `set -e`). It runs as the studio's user
with the same view of processes as the agent.
*Alternatives:* a sidecar container (would need `shareProcessNamespace` and
cannot stop PostgreSQL through `pg_ctlcluster`); shell (the SSE stream and JSON
are awkward without `jq`, and mawk lacks what the address matching wants).

The loop's output, stderr included, goes through
`tee -a /tmp/appstudio-reaper.log` to the container's stdout, which promtail
ships to Loki. Each reaper line starts with `appstudio-reaper:`, so
`{namespace=~"app-studio-.*", container="opencode"} |= "appstudio-reaper:"`
finds suspends and resumes across all studios. A crash traceback and
`dev-app`'s output on resume reach both places as well.
*Alternative:* the reaper writing to both itself. Rejected: it would miss its
own crash tracebacks.

### D2. Browser presence from established connections

Count `ESTABLISHED` sockets in `/proc/net/tcp{,6}` whose local port is the
studio port and whose remote address is not loopback (`127.0.0.0/8`, `::1`,
`::ffff:127.0.0.0/8`). Any count above zero is a browser.
*Alternative:* the chrome's preview probe (`/.appstudio/probe`) as a
heartbeat. Rejected: it only runs when there is a preview hostname, browsers
throttle it in background tabs, and it would mean changing the page.
Excluding loopback keeps the reaper's own event subscription, terminals and
`kubectl exec` sessions from counting.

### D3. Agent activity from `/global/event`

Follow `/global/event` and treat every `session.*` and `message.*` event as
activity; keep a set of busy sessions from `session.status` (anything but
`idle` is busy) and `session.idle`. The agent is idle when that set is empty
and no such event arrived for 30 minutes. Reconnect after 1 s on any error,
keeping the busy set. Other event types (`server.*`, `project.updated`, MCP
status changes the reaper causes) are ignored, so the reaper does not keep
itself awake.

The stream alone misses a turn that starts while it reconnects (or before the
reaper's first connection), and a tool call can run silent for longer than the
threshold. So before suspending, the reaper asks `GET /session/status` for each
directory with a running `playwright-mcp`; any session not `idle` cancels the
suspend and counts as activity. Those are the only directories a working
session can be in.
*Alternatives:* polling `/session/status` instead of the stream (per directory,
so every app and worktree would need enumerating, and querying a directory
creates an instance for it); `GET /api/session/active` (empty during a turn).

### D4. Suspend: stop leftovers by process group, disconnect MCP servers

Every 5 s (a `/proc` read): if a browser is connected, note the time; if both
the browser and the agent have been away 30 minutes and no session is busy
(D3), suspend once:

1. Record the preview's directory (the working directory of the process in
   `dev-app`'s pidfile) and the working directory of each `playwright-mcp`
   that is a child of opencode, in `/tmp/appstudio-reaper.state`.
2. `pg_ctlcluster 18 main stop` (a clean shutdown).
3. TERM every process group with a member whose parent is PID 1, except
   opencode's and the reaper's own; KILL what is left after 10 s. This covers
   whatever the agent started, on any port, and nothing still attached to a
   live parent (open terminals, opencode's children, `kubectl exec`).
4. `POST /mcp/playwright/disconnect?directory=<dir>` for each recorded MCP
   directory, which stops its `playwright-mcp` and Chrome.
5. Remove `dev-app`'s pidfile.

*Alternatives:* stop only what holds the preview port (misses apps on other
ports, the 0.4 GB case found live); stop only listening processes (misses
background jobs that do not listen); `POST /instance/dispose` (closes the
instance's terminals and ends a running turn).

### D5. Resume on the first browser connection

When a suspended studio sees a browser:

1. `POST /mcp/playwright/connect?directory=<dir>` for each recorded MCP
   directory, so the agent has its browser tools before the owner's first
   prompt. A disconnected server stays `disabled` until then.
2. Start `dev-app` in the recorded preview directory, in its own session, and
   `wait()` on it from a thread so it does not stay a zombie when it exits.
   `dev-app` starts PostgreSQL and Garage itself.
3. Remove the state file.

The reaper reads the state file on start, so one restarted while the studio
is suspended still resumes it. `/tmp` does not survive a pod restart, and
neither does a `disabled` MCP server.

### D6. Playwright MCP's own idle timeout at 10 minutes

`--idle-timeout 600000` on the `playwright-mcp` command in `opencode.json`.
The browser runs `--isolated`, so a relaunch loses no state the agent could
rely on. Independent of D4; covers an owner who keeps the tab open all day.

## Risks / Trade-offs

- [A deliberate long job started with `nohup` in a terminal that was then
  closed is stopped after 30 idle minutes] → Accepted; it is the leftover the
  reaper exists for. An opt-out (an environment marker) can follow if owners
  need it.
- [A laptop that sleeps with the tab open may keep Traefik's upstream
  connection open for a while] → Only delays suspending; untested.
- [The stream misses the start of a turn (reconnecting, or before the
  reaper's first connection)] → The status check before suspending (D3)
  catches it; observed in testing, where a missed turn was cut short without it.
- [The owner prompts in the seconds between connecting and the reaper's next
  check, before MCP servers are reconnected] → At most 5 s; that turn lacks
  the browser tools.
- [opencode's API or event names change on an upgrade] → The README's coupling
  note lists them; the opencode version is pinned in the image.
- [The reaper dies] → The restart loop brings it back; a dead reaper only
  means nothing is suspended, as today.

## Migration Plan

New image and chart versions; studios pick them up on their next template
upgrade. Rollback is the previous template; nothing persistent changes.
