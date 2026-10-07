# bucket-exporter — deployment bucket sizes from Garage

Reads every `dep-<deployment id>` bucket's size from one environment's Garage,
one bucket per call at `READ_RATE`, recently written buckets first, and
publishes it on `:9100/metrics` for the usage sampler to read from Prometheus.
Runs beside Garage (`tf/app/garage/bucket-exporter.tf`) with a token scoped to
`ListBuckets` and `GetBucketInfo`.

Spec: [bucket-size-exporter](../../openspec/specs/bucket-size-exporter/spec.md),
[object-storage-usage](../../openspec/specs/object-storage-usage/spec.md) ·
Rationale: [meter-object-storage](../../openspec/changes/meter-object-storage/design.md)

## Configuration

Environment variables; see `config.go`.

| Variable | Default |
|---|---|
| `GARAGE_ADMIN_URL`, `GARAGE_ADMIN_TOKEN` | required |
| `GARAGE_NAMESPACE` | required; scopes the Loki and Prometheus queries |
| `LOKI_URL` | required |
| `PROMETHEUS_URL` | unset: a restart starts without sizes |
| `READ_RATE` | `0.2` calls/s |
| `REFRESH_INTERVAL` | `5m` |
| `LOKI_LAG` | `1m` |
| `LISTEN_ADDR` | `:9100` |

## Running and testing

```sh
cd daemons/bucket-exporter && GOWORK=off go vet ./... && GOWORK=off go test ./...
```

`testdata/` holds Garage v2.3.0's admin API responses and request log lines,
recorded on dev. A Garage upgrade that changes the request log's format fails
`TestTheRegularExpressionMatchesGarageV230RequestLines` once re-recorded, and
`caelus_bucket_exporter_activity_signal_ok` drops to 0 in production.

Against a live instance, with port-forwards to Garage's admin port, Loki and
Prometheus:

```sh
GARAGE_ADMIN_URL=http://localhost:3903 GARAGE_ADMIN_TOKEN=… \
GARAGE_NAMESPACE=caelus-garage-dev LOKI_URL=http://localhost:3100 \
PROMETHEUS_URL=http://localhost:9090 READ_RATE=1 go run .
curl -s localhost:9100/metrics
```
