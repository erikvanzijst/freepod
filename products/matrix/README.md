# Matrix / Tuwunel Helm Chart

Custom Helm chart for deploying [Tuwunel](https://matrix-construct.github.io/tuwunel/) in Caelus.

## Design intent

- Single-replica `StatefulSet` with persistent storage for RocksDB data.
- One domain value (`serverName`) drives both ingress host and Matrix `server_name`.
- Federation is expected via HTTPS `:443` + `.well-known` endpoints (no explicit `8448` service).
- Curated config surface with `extraEnv` for advanced overrides.

## Quick test

```bash
helm lint ./products/matrix/chart
helm template matrix ./products/matrix/chart --set serverName=matrix.app.example.com
```

## Key values

| Value                           | Description                             | Default                            |
|---------------------------------|-----------------------------------------|------------------------------------|
| `serverName`                    | Matrix homeserver name and ingress host | `matrix.example.com`               |
| `image.repository`              | Tuwunel image repository                | `ghcr.io/matrix-construct/tuwunel` |
| `image.tag`                     | Tuwunel image tag                       | `v1.5.0`                           |
| `service.port`                  | Kubernetes Service port                 | `80`                               |
| `service.targetPort`            | Tuwunel container listen port           | `6167`                             |
| `ingress.enabled`               | Enable ingress creation                 | `true`                             |
| `ingress.className`             | Ingress class                           | `traefik`                          |
| `persistence.enabled`           | Enable persistent data                  | `true`                             |
| `persistence.size`              | Data PVC size                           | `10Gi`                             |
| `persistence.storageClassName`  | StorageClass (`null` = cluster default) | `null`                             |
| `registration.token`            | Static registration token               | `""`                               |
| `registration.tokenSecretRef.*` | Existing secret reference for token     | empty                              |
| `federation.enabled`            | Enable federation behavior in Tuwunel   | `true`                             |
| `trustedServers`                | Notary trusted key servers              | `["matrix.org"]`                   |
| `extraEnv`                      | Extra container env entries             | `[]`                               |

## Registration behavior

Registration is enabled implicitly when either of these is set:

1. `registration.token`, or
2. `registration.tokenSecretRef.name` + `registration.tokenSecretRef.key`

If neither is set, registration remains closed.

When `registration.token` is set (and `tokenSecretRef.name` is empty), the chart
creates a Secret automatically.

Set only one source at a time: inline token or existing secret reference.

## Automatic well-known wiring

The chart always injects:

- `TUWUNEL_WELL_KNOWN__CLIENT=https://<serverName>`
- `TUWUNEL_WELL_KNOWN__SERVER=<serverName>:443`

This supports federation on a single hostname with TLS termination handled upstream.

## Build and publish

Published to `oci://ghcr.io/erikvanzijst/freepod/charts/matrix` by
[`scripts/publish-charts.sh`](../../scripts/publish-charts.sh), which CI runs on
every merge to `master`: bump `version` in `chart/Chart.yaml` and that version
is published. To publish by hand, from the repository root:

```bash
./scripts/publish-charts.sh matrix
```

## Caelus product template

Use empty default user values:

```json
{
}
```

For the Caelus Admin product template, use the following values schema:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "matrix values",
  "type": "object",
  "properties": {
    "serverName": {
      "title": "DomainName",
      "description": "The hostname of your homeserver, e.g. `matrix.app.deprutser.be`.",
      "type": "string",
      "minLength": 1,
      "maxLength": 253,
      "pattern": "^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$"
    },
    "registration": {
      "type": "object",
      "properties": {
        "token": {
          "title": "Registration token",
          "type": "string",
          "description": "The registration token for your homeserver to allow new signups. When left empty, registration is disabled."
        }
      },
      "required": [
        "token"
      ],
      "additionalProperties": false
    },
    "federation": {
      "type": "object",
      "properties": {
        "enabled": {
          "type": "boolean"
        }
      },
      "required": [
        "enabled"
      ],
      "additionalProperties": false
    }
  },
  "required": [
    "serverName",
    "registration",
    "federation"
  ],
  "additionalProperties": false
}
```
