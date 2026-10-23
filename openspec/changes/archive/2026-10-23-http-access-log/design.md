## Context

`freepod log` is served by `GET …/deployments/{id}/log` (`api/app/api/users.py`), built on
`api/app/services/deployment_logs.py` (policy) over `api/app/services/loki.py` (transport). The
policy module has two halves:

- **Pod-log specific:** `LogTarget`, `resolve_target` (authorization and release lookup),
  `build_selector`, and the `{ts, line, release}` event.
- **Generic:** the resume-timestamp parser, SSE framing, the keepalive, the inclusive-resume
  `_Cursor`, `fetch_initial` (the first batch is fetched before the response starts, so a 503 is
  still possible), the `stream_log` follow loop with lifetime cap and stalled-cursor handling, and
  the per-user `_StreamRegistry`.

The endpoint's `since` parameter is already taken: it is the nanosecond resume point.

After `traefik-json-access-logs`, every access line is a JSON object in
`{namespace="kube-system", container="traefik"}` with stream labels `router`, `status` and `method`.

## Goals / Non-Goals

**Goals:**

- One service that answers "this deployment's requests, from here, optionally following", usable
  unchanged by a later dashboard view.
- The pod log and the access log share one implementation of cursor, resume, keepalive, follow loop
  and stream limit.

**Non-Goals:**

- Server-side search, filtering by status or path, or aggregation. Users grep the output.
- Caching. The selector resolves from one row read, and Loki has its own results cache.
- Release attribution for requests.
- Serving the CLF lines written before the JSON switch.

## Decisions

### D1: A deployment's requests are selected by router-name prefix

Traefik's Kubernetes Ingress provider (v3.7.13, `pkg/provider/kubernetes/ingress/kubernetes.go`)
names each router:

```
Normalize(ingress.Namespace + "-" + ingress.Name + "-" + rule.Host + path) + "@kubernetes"
```

`Normalize` turns each run of non-alphanumeric characters into one `-` and doesn't truncate. Rules
that would collide within one Ingress get `-<10 hex>` appended. Every catalog chart names its
Ingresses `<release>-…`, and the release name is `deployment.name`, the same fact the pod log's
`instance` label relies on. So every router a deployment owns, across Ingresses, hosts and paths,
starts with `<namespace>-<name>-`. The selector is:

```
{namespace="kube-system", container="traefik", router=~"<ns>-<name>-.+@kubernetes(crd)?"}
```

- **Anchored, label-only.** LogQL anchors label regexes, and `router` is a stream label, so this is
  an index lookup, not a line scan.
- **The trailing `-` after the name** stops `…-ab12cd` from matching `…-ab12cd9`.
- **`(crd)?`** covers a chart that renders an IngressRoute (`<ns>-<name>-<hash>@kubernetescrd`). No
  catalog chart does today.
- **Both values are platform-generated `[a-z0-9-]`,** and are regex-escaped anyway. The hostname
  and path, the only parts a tenant influences, come after the prefix, so they can't forge it.
- **Why another tenant can't match.** Namespaces are `<product>-<email>-<9 random>` and names are
  `<product>-<6 random>`. Matching another deployment's prefix means reproducing its random
  suffixes. In a legacy shared namespace, it would also need a sibling name that starts with this
  name plus `-`, which the fixed-length suffix rules out.

Alternatives considered:

- **Match on `RequestHost` against the deployment's hostnames.** Hostnames move between deployments
  (a custom domain re-pointed takes its history with it), and the platform's redirect routers
  would need excluding by hand.
- **List the deployment's Ingress objects at request time and build exact router names.** This adds
  a Kubernetes API call to every read and still depends on the same naming scheme.
- **A Promtail-side deployment label.** Promtail can't join a Traefik line to the Ingress that
  produced it.

The dependency on Traefik's naming is recorded as a comment beside the Traefik chart version in
`tf/deps/system/helm/traefik/variables.tf`, the place an upgrade starts. If the scheme ever changed,
reads would return nothing rather than another tenant's requests.

### D2: Generic streaming moves to a shared module

The generic half of `deployment_logs.py` moves to `api/app/services/log_stream.py`. A log source is
described by:

- **a selector** (string),
- **an event name** (`log` or `request`),
- **a `render(entry) -> dict | None` function.** `None` means "skip this line".

`fetch_initial`, the follow loop, `_Cursor`, SSE helpers and `stream_registry` take that
description. `deployment_logs.py` keeps target resolution, the release logic and its selector, and
`http_logs.py` adds its selector and record parser. The same `stream_registry` instance serves
both endpoints, which is what makes the limit shared.

**Skipped lines still advance the cursor.** Otherwise a run of unparseable lines at the cursor would
be re-fetched every poll and, at a full batch, would trip the stalled-cursor error. This matters on
day one, when the window can include CLF lines.

A later UI consumes the same SSE endpoint, so there is no second service API to keep in step.

### D3: The request record is mapped field by field

`http_logs.render` does `json.loads` on the line and builds the record from named keys only:

| Record | Traefik key | Notes |
|---|---|---|
| `ts` | Loki entry timestamp | string, nanoseconds |
| `time` | `StartUTC` | RFC 3339, UTC |
| `host` | `RequestHost` | |
| `remote_addr` | `ClientHost` | |
| `method` | `RequestMethod` | |
| `path` | `RequestPath` | includes the query string |
| `protocol` | `RequestProtocol` | |
| `status` | `DownstreamStatus` | int |
| `bytes` | `DownstreamContentSize` | int |
| `duration_ms` | `Duration` | ns ÷ 1e6, rounded to 3 decimals |
| `referer` | `request_Referer` | `null` if absent |
| `user_agent` | `request_User-Agent` | `null` if absent |

A line that isn't JSON, or lacks `RequestMethod`, `DownstreamStatus` or `StartUTC`, renders to
`None`. Unknown keys are never copied, which is the allowlist the spec requires. The SSE event is
`event: request`, with `id:` mirroring `ts` as the pod log does.

Native Loki objects were considered for `--json` and rejected. Loki groups entries by stream, its
split between labels and structured metadata is an ingest detail, and a denylist of "platform
fields" would leak anything added to the line later.

### D4: The window is a new `lookback` parameter in seconds

`since` stays the nanosecond resume point on both endpoints, so the existing client contract
doesn't change. `lookback` is an integer, at least 1 and at most `log_initial_lookback_seconds`
(14 days, matching Loki retention); otherwise the request gets 400 with the maximum stated.

`fetch_initial` already runs a backward query from `now - log_initial_lookback_seconds` with the
tail as limit. A lookback narrows that start, which gives "newest N in the window" with no new
query shape. When `since` is supplied, it wins, as today. The tail default (200) and cap (5000) are
unchanged.

The client sends the duration; the server computes the start from its own clock. That keeps
client clock skew out of the window.

### D5: Text formatting lives in the CLI

The `freepod` package imports nothing from `api/`, and the UI will render a table, not text, so
Combined Log Format is formatted client-side from the record:

```
{remote_addr} - - [{time as %d/%b/%Y:%H:%M:%S +0000}] "{method} {path} {protocol}" {status} {bytes} "{referer}" "{user_agent}"
```

- **Month names** come from a fixed English list, not `%b`, so output doesn't depend on locale.
- **Escaping follows Apache's rules:** `\` → `\\`, `"` → `\"`, control characters → `\xHH`. This
  applies to `path`, `referer` and `user_agent`.
- **Absent referer or user agent** prints `-`.
- **Zero bytes** prints `0`, nginx-style, which every common parser accepts.
- **`-t`** prefixes the event's `ts` in the existing ISO format, matching pod logs.

`--json` prints `json.dumps(event_data, separators=(",", ":"), ensure_ascii=False)`, the server's
record unchanged, for either log type.

`--since` is parsed client-side with `^[1-9][0-9]*[smhd]$` and sent as `lookback`. `--http` with
`-r` is a `click.UsageError`.

## Risks / Trade-offs

- [Traefik changes its router-naming scheme] → Reads return nothing, never another tenant's
  requests. The comment beside the chart version prompts a check on upgrade.
- [A catalog chart names an Ingress without the release prefix] → Only that deployment's access
  log is empty. Isolation doesn't depend on the convention.
- [A very busy deployment outpaces the follow loop] → Each 2 s poll fetches up to 5000 lines, about
  2500 requests/s sustained. Beyond that, the stream lags rather than drops lines, since the cursor
  only moves forward over delivered or skipped lines.
- [A new CLI against an API without the change] → `/http-log` answers 404, and an older server
  ignores `lookback`, so `--since` would silently show the default tail. Deploy the API to both
  environments before publishing the client.
- [Visitor IPs, user agents and referers shown to tenants] → These are the tenant's own visitors,
  and comparable platforms expose the same fields. Redacting later is a change to the record
  mapping in one place.

## Migration Plan

1. `traefik-json-access-logs` live on both environments.
2. Deploy the API: the refactor, `lookback` and `/http-log`.
3. Publish the client.

Rollback is redeploying the previous API; the client degrades as described above.
