# Tasks

## 1. Traefik emits allowlisted JSON

- [x] 1.1 Set `accessLog.format: json` and the field and header allowlist from design D2 in
  `tf/deps/system/helm/traefik/values.yaml.tftpl`. Update the comment above `accessLog` to describe
  the JSON format and why the lists are allowlists. Verify by running the pinned v3.7.13 binary
  locally with the same `accessLog` block and a request carrying `Cookie`, `Authorization`,
  `User-Agent` and `Referer`: the line holds exactly the D2 fields plus `request_User-Agent` and
  `request_Referer`. Note whether `level`, `msg` and `time` survive.

## 2. Promtail parses JSON

- [x] 2.1 Replace the CLF `regex` and `structured_metadata` stages in Promtail's Traefik `match`
  stage (`tf/deps/loki/main.tf`) with the D3 line-filtered selector, a `json` stage, and a `labels`
  stage mapping `RequestMethod`, `DownstreamStatus` and `RouterName` to `method`, `status` and
  `router`. Update the stage's comment. Verify with `terraform plan` in `tf/deps` that only the
  Promtail config and the Traefik release change.

## 3. Dashboard

- [x] 3.1 Update the Traefik access-log panel in `tf/deps/prometheus/dashboards/deployment.json`
  to the D4 query. Verify the JSON stays valid (`python3 -m json.tool`) and that the panel's
  `$status` and `$search` variables are still referenced.

## 4. Rollout and verification

- [x] 4.1 Apply `tf/deps` (check `terraform workspace show` first). Verify with LogQL over the last
  five minutes: `{namespace="kube-system", container="traefik", router=~".+"}` returns JSON lines
  with `method`, `status` and `router` labels; no line contains `Cookie`, `Authorization` or
  `ServiceURL`; and `count_over_time` for that selector is non-zero for a tenant router.
- [x] 4.2 Open the Freepod: deployment dashboard for a deployment receiving traffic and verify the
  access-log panel shows summary lines, and that the `$status` filter (4xx and 5xx) narrows them.

## Workflow follow-up

- About a week after rollout, re-measure `sum(bytes_over_time({namespace="kube-system",
  container="traefik"}[24h]))` against total ingest and Loki's on-disk size. If the 3 GiB budget
  in `tf/deps/loki/main.tf` is threatened, revisit the field list or retention.
- Archive the change and sync its spec delta.
