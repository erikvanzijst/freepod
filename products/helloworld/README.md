# helloworld

Demo Helm chart for Caelus architecture work.

## What it deploys

- PVC for persistent data
- Deployment with:
  - init container writing `/data/index.html` from `.Values.user.message`
  - nginx serving that file from PVC
- Service
- Optional Ingress

## Quick test

```bash
helm template demo ./products/helloworld/chart \
  --set ingress.enabled=true \
  --set ingress.className=traefik \
  --set ingress.host=hello.example.com \
  --set user.message="Hello from values"
```

## Build and publish

Published to `oci://ghcr.io/erikvanzijst/freepod/charts/helloworld` by
[`scripts/publish-charts.sh`](../../scripts/publish-charts.sh), which CI runs on
every merge to `master`: bump `version` in `chart/Chart.yaml` and that version
is published. To publish by hand, from the repository root:

```bash
./scripts/publish-charts.sh helloworld
```

## Deploy to k3s

```bash
helm install helloworld oci://ghcr.io/erikvanzijst/freepod/charts/helloworld \
  --kubeconfig ./kubeconfigs/k3s-dev.yaml \
  --version 0.2.1 \
  --namespace hello2 \
  --create-namespace \
  --set ingress.host=hello2.app.deprutser.be
```

## Caelus product template

Default user values:

```json
{
    "user": {
        "message": "Hello World from Caelus"
    }
}
```

For the Caelus Admin product template, use the following values schema:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "ingress": {
      "type": "object",
      "properties": {
        "host": {
          "title": "domainname",
          "type": "string",
          "minLength": 1,
          "maxLength": 64,
          "pattern": "^((?!-)(xn--)?[a-z0-9][a-z0-9-_]{0,61}[a-z0-9]?\\.)+(xn--)?[a-z0-9-]{2,}$",
          "description": "The domainname for the new application"
        }
      },
      "required": [
        "host"
      ],
      "additionalProperties": false
    },
    "user": {
      "type": "object",
      "properties": {
        "message": {
          "type": "string",
          "maxLength": 2000,
          "description": "Text in the generated index.html"
        }
      },
      "additionalProperties": false
    }
  },
  "required": [
    "ingress"
  ],
  "additionalProperties": false
}
```