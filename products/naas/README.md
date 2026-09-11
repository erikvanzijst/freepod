# NaaS — No As A Service

A service that serves a random "NO" meme image on every request.

Every time you hit the endpoint, you get a different NO meme — Grumpy Cat,
Michael Scott, Darth Vader, Dikembe Mutombo, and more.

## How it works

- A lightweight Python HTTP server runs inside a `python:3.12-alpine` container
- 11 classic NO meme images are baked into the chart as a ConfigMap (`binaryData`)
- Each HTTP request returns a randomly selected image with appropriate headers
- `Cache-Control: no-store` ensures every refresh gives you a fresh NO
- The `X-No-Meme` response header tells you which meme you got

## Endpoints

| Path       | Description                  |
|------------|------------------------------|
| `/`        | Random NO meme image         |
| `/healthz` | Health check (returns `ok`)  |

## Quick test

```bash
helm template demo ./products/naas/chart \
  --set ingress.host=no.example.com
```

## Build and publish

Published to `oci://ghcr.io/erikvanzijst/freepod/charts/naas` by
[`scripts/publish-charts.sh`](../../scripts/publish-charts.sh), which CI runs on
every merge to `master`: bump `version` in `chart/Chart.yaml` and that version
is published. To publish by hand, from the repository root:

```bash
./scripts/publish-charts.sh naas
```

## Caelus product template

Create a new NaaS product in the Admin UI and add a template with the following values:

- Chart: `oci://ghcr.io/erikvanzijst/freepod/charts/naas`
- Tag: `0.1.7`

Default values:

```json
{
  "ingress": {
    "enabled": true,
    "className": "traefik"
  }
}
```

### User values schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "ingress": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "host": {
          "type": "string",
          "title": "Hostname",
          "minLength": 1,
          "description": "The hostname name for this glorious service"
        }
      },
      "required": ["host"],
      "additionalProperties": false
    }
  },
  "required": ["ingress"],
  "additionalProperties": false
}
```
