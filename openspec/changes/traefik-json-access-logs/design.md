## Context

Traefik (chart 41.5.0, app v3.7.13) writes its access log to stdout in its CLF variant: combined
log format followed by request count, router name, upstream URL and duration. Promtail parses that
with one regex inside a `match` stage on `{namespace="kube-system", container="traefik"}`. It
promotes `method`, `status` and `router` to stream labels and `remote_addr`, `path`, `user_agent`,
`upstream` and `duration` to structured metadata.

Two consumers depend on the access log today:

- **Promtail's pipeline** in `tf/deps/loki/main.tf`.
- **The Freepod: deployment dashboard's access-log panel**: `{namespace="kube-system",
  container="traefik", router=~"$deployment-.+", status=~"$status"} |~ "(?i)$search"`.

Its latency and status panels read Traefik's Prometheus metrics, not logs. Nothing in `api/`, `ui/`
or `ops/` reads access lines.

Referer and User-Agent print as `-` because Traefik's `accessLog.fields.headers.defaultMode`
defaults to `drop`.

## Goals / Non-Goals

**Goals:**

- One JSON object per access-log line, with only the fields the access log needs.
- Unchanged label names and meanings, so existing selectors keep working.

**Non-Goals:**

- Changing Traefik's own (non-access) log format.
- Backfilling or rewriting CLF lines already in the store.
- Changing Loki retention.

## Decisions

### D1: JSON lines, not an extended CLF

Traefik's `accessLog.format: json` emits every field under a stable name, including `RequestHost`,
which CLF can't carry. Parsing becomes a Promtail `json` stage rather than a regex, and the
tenant-facing reader in `http-access-log` uses an ordinary JSON parse rather than a second copy of
that regex.

An extended CLF (prefixing the virtual host, nginx `vhost_combined` style) was the alternative. It
keeps lines human-readable in `kubectl logs`, but every reader still needs its own regex, and
quoting rules for fields like user agents are a parsing hazard JSON doesn't have.

### D2: An allowlist, set with `fields.defaultMode: drop`

Field selection is set at the source:

```yaml
accessLog:
  format: json
  fields:
    defaultMode: drop
    names:
      StartUTC: keep
      ClientHost: keep
      RequestHost: keep
      RequestMethod: keep
      RequestPath: keep
      RequestProtocol: keep
      DownstreamStatus: keep
      DownstreamContentSize: keep
      Duration: keep
      RouterName: keep
    headers:
      defaultMode: drop
      names:
        User-Agent: keep
        Referer: keep
```

`defaultMode: drop` with explicit `keep`s, rather than `keep` with explicit `drop`s, means a field
added in a later Traefik release doesn't start appearing in the store unannounced. Headers follow
the same rule. Keeping all headers was ruled out because it would store `Cookie` and
`Authorization`, which are credentials.

Traefik writes kept headers as `request_User-Agent` and `request_Referer`, and writes `Duration` in
nanoseconds. Both were checked against a v3.7.13 binary with this exact header configuration. The
logger's own `level`, `msg` and `time` keys may not be governed by `fields.names`; whether they
survive `defaultMode: drop` is checked at implementation time (task 1.1) and accepted either way.

Measured on the live cluster: about 230 bytes per CLF line today, about 1.1 KB per JSON line with
every field, and about 600 bytes per line trimmed as above with both headers.

### D3: Promtail parses JSON and labels from it, with no structured metadata

The `match` stage keeps its selector and adds a line filter so only access lines enter it:

```
{namespace="kube-system", container="traefik"} |= "\"RouterName\""
```

Inside it, a `json` stage extracts `RequestMethod`, `DownstreamStatus` and `RouterName`, and a
`labels` stage maps them to `method`, `status` and `router`. Keeping the label names means the
dashboard's selector and its `$status` variable keep working without edits.

The structured-metadata stage is dropped for access lines. With JSON lines every field is
available to LogQL through `| json`, so duplicating five of them as metadata only costs index
space.

A request that matched no router has no `RouterName` key, so it neither enters the match nor gets a
`router` label. Today such lines carry `router="-"`. Nothing selects on that value.

### D4: The dashboard panel renders a summary line

The panel query becomes:

```
{namespace="kube-system", container="traefik", router=~"$deployment-.+", status=~"$status"}
  |~ "(?i)$search"
  | json
  | line_format "{{.ClientHost}} {{.RequestMethod}} {{.RequestHost}}{{.RequestPath}} {{.DownstreamStatus}} {{.Duration}}"
```

The search filter stays ahead of `| json` so it still matches raw text, as it does today. The panel
belongs to the dashboard introduced by change `deployment-dashboards`. Its spec there only requires
that access lines appear, which this doesn't alter, so no delta is needed against that change.

## Risks / Trade-offs

- [Raw ingest grows by about half] → It stays well inside the 3 GiB budget derived in
  `tf/deps/loki/main.tf` at 14-day retention. Re-measure a week after rollout (see tasks).
- [Mixed formats in the store for up to 14 days] → The dashboard panel's `| json` fails on CLF lines
  and Grafana shows them with a parse-error label, which is readable enough until retention removes
  them. The tenant reader skips non-JSON lines, and the feature ships with no history expectation.
- [A brief window between the Traefik and Promtail rollouts] → During it, access lines are either
  CLF passing through the new JSON match unlabeled, or JSON failing the old regex. Both are
  collected, just not labeled. Apply both in one `terraform apply` to keep the window short.
- [Personal data in the store grows] → User-Agent and Referer are added to the client IP already
  stored, under the same retention. The privacy policy already lists access records.

## Migration Plan

1. Apply `tf/deps` with the Traefik values and the Promtail pipeline together.
2. Confirm new access lines are JSON, labeled with `router`, `status` and `method`, and contain
   neither a cookie nor an upstream address. Confirm the dashboard panel renders.
3. Rollback: revert both files and re-apply. JSON lines written in between keep their labels,
   because labels were assigned at ingest.
