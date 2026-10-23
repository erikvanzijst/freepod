## Why

Traefik's access log is about to become a tenant-facing feature (`freepod log --http`, change
`http-access-log`), and its current Common Log Format output can't support it. Request headers are
dropped, so Referer and User-Agent are always `-`. There's no request host, so a deployment that
serves several hostnames can't tell them apart. And every field is recovered by a single long
Promtail regex, which any future reader would have to copy.

## What Changes

- Traefik writes its access log as **JSON lines** instead of Common Log Format.
- Access-log fields are an **allowlist**: only what a request record needs is kept. Everything else
  Traefik can emit, such as client port, upstream service address, retry counts and entrypoint, is
  dropped at the source.
- Request headers are dropped by default. **Only `User-Agent` and `Referer` are kept**, so cookies,
  authorization headers and every other header never reach the log store.
- Promtail parses the access log with a JSON stage instead of the CLF regex. `method`, `status` and
  `router` remain stream labels, with the same names and meanings as today. Structured metadata for
  access lines is no longer extracted, because every field is in the JSON line.
- The **Freepod: deployment** Grafana dashboard's Traefik access-log panel renders each JSON line as
  a readable one-line summary, so operators don't read raw JSON.
- No backfill: access lines written before the switch stay in CLF until the store's retention
  removes them.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `pod-log-aggregation`: the parsed-Traefik-access-log requirement changes from CLF parsing to
  JSON-line parsing, gains the field and header allowlist, and makes the `router`, `status` and
  `method` labels a contract, since the access-log reader in `http-access-log` will depend on
  `router`.

## Impact

- `tf/deps/system/helm/traefik/values.yaml.tftpl`: `accessLog.format` and `accessLog.fields`.
- `tf/deps/loki/main.tf`: Promtail's Traefik match stage.
- `tf/deps/prometheus/dashboards/deployment.json`: the access-log panel query.
- Log volume: a trimmed JSON line with both headers is roughly 2.5× today's CLF line. Access lines
  are about a third of raw ingest, so total raw ingest grows by about half. That stays well inside
  the store's 3 GiB budget at the current 14-day retention, but it needs measuring once the change
  is live.
- Operators reading `kubectl logs deploy/traefik` see JSON instead of CLF.
- Privacy: visitor User-Agent and Referer are newly stored, alongside the client IP that is already
  collected. The privacy policy already lists "log and access records"; retention is unchanged.
