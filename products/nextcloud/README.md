# Nextcloud

A self-contained Nextcloud chart: it renders the Nextcloud application and a
bundled PostgreSQL database directly, on the official `nextcloud` and `postgres`
images. Its only dependency is Freepod's `ssh-sidecar` library chart, which adds
read-only file access to the data volume.

## What it deploys

| Component   | Object(s)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
|-------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Nextcloud   | Deployment `<release>-nextcloud` (+ SSH sidecar, + wait-for-DB init), Service `<release>-nextcloud` `:8080→80`                                                                                                                                                                                                                                                                                                                                                                                  |
| PostgreSQL  | StatefulSet `<release>-postgresql` on `postgres:17-alpine` + headless Service + Secret `<release>-db` (auto-generated password); data on PVC `data-<release>-postgresql-0`                                                                                                                                                                                                                                                                                                                                 |
| Data        | PVC `<release>-data` (plan-sized), mounted into the app via subPaths (`html`, `data`, `config`, `custom_apps`, `themes`, `tmp`)                                                                                                                                                                                                                                                                                                                                                                            |
| App secrets | Secret `<release>-app` (admin bootstrap + SMTP)                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| App config  | ConfigMap `<release>-config` (non-secret env via `envFrom`) + ConfigMap `<release>-hooks` (a `before-starting` entrypoint hook that runs `occ db:add-missing-indices/columns/primary-keys` and `occ maintenance:repair --include-expensive` after each upgrade, clearing the "missing indices" and "mimetype migrations available" admin warnings, and rewrites the persisted `trusted_domains` from `NEXTCLOUD_TRUSTED_DOMAINS` so a hostname change takes effect — the image applies that variable at install time only) + ConfigMap `<release>-apache` (`hsts.conf` so Nextcloud's server-side HTTP-headers check sees HSTS; edge Traefik still owns the browser-facing header) |
| Ingress     | `<release>-ingress` (per-deployment TLS via `caelus.ingress.tls`)                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| File access | Service `<release>-ssh` only (`ssh-sidecar`); session rooted at `volume:/data`, the `data` subPath alone — the PVC root also holds `config/config.php`                                                                                                                                                                                                                                                                                                                                                                                                       |

The bundled PostgreSQL password is generated on first install and reused from the
`<release>-db` Secret on upgrade, so it never rotates a live credential. Set
`postgresql.auth.password` to pin an explicit value instead.

## Manual install

```bash
helm dependency build products/nextcloud/chart
helm upgrade --install nextcloud products/nextcloud/chart \
  --namespace nextcloud --create-namespace \
  --set host=cloud.example.com
```

`image.tag` defaults to `<appVersion>-apache`. Set `admin.password` and the
`smtp.*` values for a real deployment (defaults are dev-only).

## Build and publish

Published to `oci://ghcr.io/erikvanzijst/freepod/charts/nextcloud` by
[`scripts/publish-charts.sh`](../../scripts/publish-charts.sh), which CI runs on
every merge to `master`: bump `version` in `chart/Chart.yaml` and that version
is published. To publish by hand, from the repository root:

```bash
./scripts/publish-charts.sh nextcloud
```

The published chart is then referenced from a Caelus product template:

| Field               | Value                                                                               |
|---------------------|-------------------------------------------------------------------------------------|
| Chart ref           | `oci://ghcr.io/erikvanzijst/freepod/charts/nextcloud`                               |
| Chart version       | `0.2.2`                                                                             |
| User values schema  | see [User values schema](#user-values-schema) below                                 |
| Default Helm values | see [Default values (system_values_json)](#default-values-system_values_json) below |

## User values schema

Defines the form fields on the user-facing deployment dialog — the only values a
tenant may override when creating a Nextcloud instance. Everything else (images,
storage sizing, DB credentials, admin/SMTP secrets, TLS) is operator- or
plan-controlled and is not exposed here. The one tenant-chosen value is the
hostname:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "host": {
      "title": "Hostname",
      "type": "string",
      "minLength": 1,
      "description": "The hostname for your Nextcloud instance"
    }
  },
  "required": ["host"],
  "additionalProperties": false
}
```

## Default values (system_values_json)

The admin configures a static default-values blob (`system_values_json`) on the
product template. It is merged over the chart's `values.yaml` for every
deployment created from that template, and is where operator-wide settings live —
SMTP, the admin bootstrap account, and a pinned image tag. It is not where
per-tenant values (the hostname), plan-injected values (storage sizing), or the
auto-generated DB password go.

```json
{
  "image": {
    "tag": "32.0.6-apache"
  },
  "admin": {
    "username": "admin"
  },
  "smtp": {
    "host": "smtp.mailer.svc.cluster.local",
    "port": 25,
    "fromAddress": "nextcloud",
    "domain": "freepod.eu"
  }
}
```

`image.tag` pins the Nextcloud release, including the `-apache` suffix (otherwise
it floats on `<appVersion>-apache`); leave `smtp.host` empty to disable mail.
`admin.password` seeds the first-run admin account and is shared by every
deployment created from the template.
