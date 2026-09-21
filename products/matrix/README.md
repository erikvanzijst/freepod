# Matrix / Tuwunel Helm Chart

Custom Helm chart for deploying [Tuwunel](https://matrix-construct.github.io/tuwunel/) in Caelus.

## Design intent

- Single-replica `StatefulSet` with persistent storage for RocksDB data.
- One domain value (`serverName`) drives both ingress host and Matrix `server_name`.
- Federation is expected via HTTPS `:443` + `.well-known` endpoints (no explicit `8448` service).
- Curated config surface with `extraEnv` for advanced overrides.
- [Element Web](https://github.com/element-hq/element-web) served at the hostname's root, locked to this homeserver.

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
| `elementWeb.enabled`            | Serve Element Web at `/`                | `true`                             |
| `elementWeb.image.tag`          | Element Web image tag                   | `v1.12.28`                         |

## Registration behavior

Registration is enabled implicitly when any of these is set:

1. `registration.token`,
2. `registration.tokenSecretRef.name` + `registration.tokenSecretRef.key`, or
3. `caelus.vars.secretName`, injected by Caelus. The token is then read from that
   Secret's `TUWUNEL_REGISTRATION_TOKEN` key, which the catalog declares as a
   required sensitive var so it never passes through Helm values.

If none is set, registration remains closed.

When `registration.token` is set (and `tokenSecretRef.name` is empty), the chart
creates a Secret automatically.

Set only one source at a time: inline token or existing secret reference.

## Automatic well-known wiring

The chart always injects:

- `TUWUNEL_WELL_KNOWN__CLIENT=https://<serverName>`
- `TUWUNEL_WELL_KNOWN__SERVER=<serverName>:443`

This supports federation on a single hostname with TLS termination handled upstream.

## Element Web

Tuwunel has no web UI, so the ingress sends everything outside `/_matrix`,
`/_tuwunel` and `/.well-known/matrix` to a stateless Element Web Deployment.
Its `config.json` is rendered from `serverName` and:

- pins the homeserver and hides the server picker (`disable_custom_urls`);
- opens on the login form instead of Element's welcome page;
- turns off guest access, email/phone login, the integration manager and bug
  reports, none of which this deployment provides;
- turns off voice and video calls (`UIFeature.voip`, `element_call.disable`),
  since Tuwunel is deployed without TURN or MatrixRTC.

On phones, Element redirects the bare URL to its own mobile guide, which
recommends Element X and deep-links it to this server. That redirect is built
into Element and not configurable.

The image's nginx runs as a non-root user and defaults to port 80, so the chart
sets `ELEMENT_WEB_PORT=8080`. A startup hook in `/docker-entrypoint.d` pins nginx
to a single worker process, since it only serves static files.

## Build and publish

Published to `oci://ghcr.io/erikvanzijst/freepod/charts/matrix` by
[`scripts/publish-charts.sh`](../../scripts/publish-charts.sh), which CI runs on
every merge to `master`: bump `version` in `chart/Chart.yaml` and that version
is published. To publish by hand, from the repository root:

```bash
./scripts/publish-charts.sh matrix
```

## Caelus product template

The product is curated: its template, including the values schema, lives in
[`products/catalog/matrix.yaml`](../catalog/matrix.yaml).
