## Why

A tenant can read their application's own output with `freepod log`, but not the requests that
reached it. Questions like "is my app getting traffic", "which paths 404" or "is a crawler hammering
me" need the platform's view of HTTP traffic, which today only operators can see in Grafana.
Railway, Vercel, Netlify and Heroku all expose per-request logs. With Traefik's access log now
emitted as JSON (change `traefik-json-access-logs`), the data needed is already in the log store.

## What Changes

- **`freepod log --http`** streams the deployment's HTTP access log. By default each request prints
  as one line in **Combined Log Format**. It works with `-f`, `-n` and `-t` exactly as pod logs do.
  `--http` with `-r` is a usage error, because ingress traffic can't be attributed to a release.
- **`freepod log --json`** prints one JSON object per line (JSONL) for both log types. Pod-log
  objects carry `ts`, `line` and `release`. Access-log objects carry a fixed set of request fields,
  including `host` and `duration_ms`, which the text format leaves out.
- **`freepod log --since <duration>`** (`30s`, `15m`, `2h`, `3d`) limits the read to a recent
  window, for both log types. At most `-n` lines are returned (default 200, capped at 5000), and
  when the window holds more, the newest are returned. A window longer than the log store's
  retention (14 days) is refused with a clear error.
- **New endpoint** `GET /api/users/{user_id}/deployments/{deployment_id}/http-log`, with the same
  transport, resume, keepalive, bounds and authorization rules as the existing log endpoint. Each
  event carries one request record.
- **New `lookback` parameter** on both log endpoints, carrying the `--since` window in seconds. The
  existing `since` parameter keeps its meaning as the resume timestamp.
- HTTP log streams count against the same per-user limit on concurrent streams as pod log streams.
- A service module serves the access log for any client, so a later dashboard view can reuse it
  unchanged. The generic streaming machinery (cursor, SSE framing, follow loop, stream registry)
  moves out of the pod-log service so both log services share it.

## Capabilities

### New Capabilities

- `deployment-http-log-api`: the REST contract for reading a deployment's HTTP access log: how
  requests are attributed to a deployment, the request record, and what is excluded.

### Modified Capabilities

- `deployment-log-api`: gains the `lookback` window.
- `cli-log`: gains `--http`, `--json` and `--since`, and the rules for which flags combine.

## Impact

- API: `api/app/services/http_logs.py` (new), a shared streaming module extracted from
  `api/app/services/deployment_logs.py`, a new route in `api/app/api/users.py`, and `lookback`
  on the existing route.
- CLI: `cli/src/freepod/cli.py` and `cli/src/freepod/logs.py`. No new dependency. The client
  version is bumped.
- Docs: `ui/docs/developers/logs-and-debugging.md`, `ui/docs/developers/cli-reference.md`,
  `cli/README.md` and the deploy skill in `cli/src/freepod/assets/SKILL.md`.
- Ops: a comment on Traefik's chart version recording that the access-log reader depends on
  Traefik's router-naming scheme.
- Depends on `traefik-json-access-logs` being live. Older access lines in CLF are skipped, not
  served.
