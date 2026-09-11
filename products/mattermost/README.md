# Mattermost Self-Contained Helm Chart

A standalone Helm chart that deploys
[Mattermost Team Edition][mm-server] with a bundled
[PostgreSQL][pg-hub] instance. Everything needed to run
Mattermost is contained in this single chart -- no external
database or platform-provided services required.

[mm-server]: https://github.com/mattermost/mattermost-server
[pg-hub]: https://hub.docker.com/_/postgres

## Why Not Wrap the Official Chart?

The official [`mattermost-team-edition`][mm-helm] chart
(v6.6.93) was evaluated as a sub-chart dependency but
ultimately could not be used. This section documents the
technical reasons so future maintainers don't repeat the
investigation.

[mm-helm]: https://github.com/mattermost/mattermost-helm/tree/master/charts/mattermost-team-edition

### The Problem

Caelus requires charts to be fully self-contained. A
Mattermost chart must bundle its own PostgreSQL instance.
The official chart supports external databases via
`externalDB.enabled: true` and
`externalDB.externalConnectionString`, but the connection
string must reference the bundled PostgreSQL service by its
Kubernetes DNS name, which includes the Helm release name
(e.g., `mattermost-postgresql`).

### Why Sub-chart Wiring Fails

The official chart's `secret-mattermost-dbsecret.yaml`
generates the DB secret like this:

```yaml
mattermost.dbsecret: {{ tpl "{{ .Values.externalDB.externalDriverType }}://{{ .Values.externalDB.externalConnectionString }}" . | b64enc }}
```

The `tpl` function evaluates the outer template expressions
(resolving `.Values.*`), but does **not** re-evaluate the
resulting string. So if `externalConnectionString` is set to
`{{ .Release.Name }}-postgresql:5432/...` in values, the
`{{ .Release.Name }}` is output as literal text -- it is not
resolved. This is because `tpl` performs a single evaluation
pass: it resolves the `.Values` references, produces an
output string, and stops. It does not recursively process
template expressions that appear in the output.

This means there is no way to set `externalConnectionString`
in `values.yaml` that dynamically references the release
name. The three workaround approaches and why each fails:

1. **Duplicate Secret override**: Create a parent-chart
   template with the same Secret name as the sub-chart's,
   containing the correct (templated) connection string.
   Helm 3 deduplicates resources by GVK+namespace+name in
   its release manifest, keeping the sub-chart's version.
   The parent chart's Secret is silently discarded.

2. **Helm hook override**: Use
   `helm.sh/hook: pre-install,post-install` annotations on
   the parent's Secret so it runs outside normal manifest
   application. The `pre-install` hook creates the correct
   Secret, but then the sub-chart's normal manifest
   overwrites it with the broken value. The `post-install`
   hook restores it, but by then Mattermost has already
   started with the wrong connection string.

3. **`extraEnvVars` override**: The sub-chart's deployment
   renders `extraEnvVars` after `MM_CONFIG` (Kubernetes uses
   last-wins for duplicate env vars). However, `extraEnvVars`
   is defined in `values.yaml`, which is not templateable --
   so the `secretKeyRef.name` cannot include
   `{{ .Release.Name }}`, and a plain `value:` field cannot
   contain the dynamic PostgreSQL hostname.

### Current Approach

This chart deploys Mattermost directly (its own Deployment,
Service, PVCs) alongside a PostgreSQL StatefulSet. This gives
full template control over the `MM_CONFIG` environment
variable, which is wired to a Secret containing the
connection string with `{{ .Release.Name }}` resolved at
template time.

## Prerequisites

- Kubernetes 1.20+
- Helm 3.13+
- Ingress controller (Traefik in Caelus)

## Architecture

```
+------------------------------------------------------+
|                  mattermost namespace                |
|                                                      |
|  +--------------+    +------------------------------+|
|  |  Ingress     |--->| Service (RELEASE-mattermost) ||
|  |  (Traefik)   |    +----------+-------------------+|
|  +--------------+               |                    |
|                                 v                    |
|  +------------------------------------------------+  |
|  |          Deployment (RELEASE-mattermost)       |  |
|  | +-----------------+  +-----------------------+ |  |
|  | | init-postgres   |  | mattermost-team-ed.   | |  |
|  | | (busybox)       |  | MM_CONFIG = DSN from  | |  |
|  | | waits for PG    |  | RELEASE-mattermost-db | |  |
|  | +-----------------+  +----------+------------+ |  |
|  +---------------------------------|--------------+  |
|                                    |                 |
|          +-------------------------+                 |
|          v                                           |
|  +------------------------------------------------+  |
|  |      StatefulSet (RELEASE-postgresql)          |  |
|  |      postgres:18                               |  |
|  |      Data: PVC (postgres-data, 10Gi)           |  |
|  +------------------------------------------------+  |
|                                                      |
|   PVCs: RELEASE-mattermost-data (10Gi)               |
|         RELEASE-mattermost-plugins (1Gi)             |
+------------------------------------------------------+
```

### Plan Storage Limits

Caelus enforces per-tenant storage quotas through plans.
During reconciliation, the reconciler reads
`storage_bytes` from the deployment's subscription plan
template and injects it into the Helm values under a
reserved `caelus.plan` namespace as a system override
(highest merge precedence, cannot be overridden by user
values):

```json
{
  "caelus": {
    "plan": {
      "storageBytes": 10737418240,
      "storageSize": "10Gi"
    }
  }
}
```

The data PVC template (`pvc.yaml`) references this value
with a fallback default:

```yaml
storage: {{ .Values.caelus.plan.storageSize | default "10Gi" }}
```

If the plan has no storage quota (`storage_bytes` is null),
the `caelus` key is not injected and the PVC falls back to
10Gi. The plugins PVC (1Gi) and PostgreSQL PVC
(`postgresql.size`) are infrastructure overhead and are not
subject to plan limits.

### Resource Inventory

| Template | Resources Created |
|---|---|
| `postgresql.yaml` | Service, Secret (PG password), StatefulSet (with PVC template) |
| `secret-db.yaml` | Secret containing the `MM_CONFIG` connection string |
| `deployment.yaml` | Deployment with init container + Mattermost container |
| `service.yaml` | ClusterIP Service exposing port 8065 |
| `pvc.yaml` | PVCs for Mattermost data and plugins |
| `ingress.yaml` | Ingress (only when `host` is set) |

### How DB Wiring Works

The `secret-db.yaml` template generates the PostgreSQL
connection string at template time:

```
postgres://{{ username }}:{{ password }}@{{ .Release.Name }}-postgresql:5432/{{ database }}?sslmode=disable&connect_timeout=10
```

This Secret is mounted as the `MM_CONFIG` environment
variable in the Mattermost container. Mattermost uses
`MM_CONFIG` as its primary configuration source -- when set
to a `postgres://` DSN, it stores all configuration in the
database rather than a local file.

An init container (`init-postgres`) blocks the Mattermost
container from starting until PostgreSQL is accepting TCP
connections, preventing startup race conditions.

## Installation

### From Local Chart

```bash
helm upgrade --install mattermost ./products/mattermost/chart \
  --namespace mattermost \
  --create-namespace \
  --set host=mattermost.prutser.freepod.eu
```

### From OCI Registry

```bash
helm upgrade --install mattermost oci://ghcr.io/erikvanzijst/freepod/charts/mattermost \
  --version 1.1.1 \
  --namespace mattermost \
  --create-namespace \
  --set host=mattermost.prutser.freepod.eu
```

### Using a Values File

Create a `values.yaml`:

```yaml
host: mattermost.prutser.freepod.eu
```

```bash
helm upgrade --install mattermost ./products/mattermost/chart \
  --namespace mattermost \
  --create-namespace \
  -f values.yaml
```

## Adding to Caelus

### 1. Package and Publish

Published to `oci://ghcr.io/erikvanzijst/freepod/charts/mattermost` by
[`scripts/publish-charts.sh`](../../scripts/publish-charts.sh), which CI runs on
every merge to `master`: bump `version` in `chart/Chart.yaml` and that version
is published. To publish by hand, from the repository root:

```bash
./scripts/publish-charts.sh mattermost
```

### 2. Register as a Product Template

In the Caelus Admin UI, create a new product (or add a
template version to an existing one) with:

| Field               | Value                                                  |
|---------------------|--------------------------------------------------------|
| Chart ref           | `oci://ghcr.io/erikvanzijst/freepod/charts/mattermost` |
| Chart version       | `1.1.1`                                                |
| User values schema  | See [values schema](#values-schema) below              |
| Default Helm values | See [system values](#system-values) below              |

The schema declares the values that end users configure
when deploying Mattermost through Caelus:

- **host** (required) -- rendered as the special
  `HostnameField` component because its `title` is
  `"hostname"`.
- **mattermost.siteName** (optional) -- overrides the
  name shown in the Mattermost UI and login screen
  (maps to `MM_TEAMSETTINGS_SITENAME`).
- **mattermost.siteDescription** (optional) -- text
  displayed above the login form (maps to
  `MM_TEAMSETTINGS_CUSTOMDESCRIPTIONTEXT`).
- **mattermost.extraEnv.TZ** (optional, default
  `Europe/Amsterdam`) -- rendered as a regular text field
  for the IANA timezone.

At deploy time, Caelus deep-merges the schema defaults
with the user-provided values and any system overrides,
then passes the result as Helm values to
`helm upgrade --install`.

### Values Schema

```json
{
  "type": "object",
  "properties": {
    "host": {
      "type": "string",
      "title": "hostname",
      "description": "The public hostname where Mattermost will be accessible."
    },
    "mattermost": {
      "type": "object",
      "properties": {
        "siteName": {
          "type": "string",
          "title": "Site name",
          "description": "Name shown in the Mattermost UI and login screen.",
          "maxLength": 30
        },
        "siteDescription": {
          "type": "string",
          "title": "Site description",
          "description": "Text displayed above the login form.",
          "maxLength": 500
        },
        "extraEnv": {
          "type": "object",
          "properties": {
            "TZ": {
              "type": "string",
              "title": "Timezone",
              "description": "IANA timezone for Mattermost (e.g. Europe/Amsterdam, America/New_York).",
              "default": "Europe/Amsterdam"
            }
          }
        }
      }
    }
  },
  "required": [
    "host"
  ]
}
```

### System Values

```json
{
  "smtp": {
    "host": "smtp.mailer.svc.cluster.local",
    "port": 25,
    "from": "mattermost@deprutser.be"
  }
}
```

## Values Reference

### Required Values

| Value  | Description                         | Example                       |
|--------|-------------------------------------|-------------------------------|
| `host` | Hostname for the Mattermost ingress | `mattermost.app.deprutser.be` |

### Mattermost Configuration

| Value                              | Default                              | Description                                                                |
|------------------------------------|--------------------------------------|----------------------------------------------------------------------------|
| `mattermost.image.repository`      | `mattermost/mattermost-team-edition` | Mattermost image                                                           |
| `mattermost.image.tag`             | `11.4.2`                             | Mattermost version                                                         |
| `mattermost.image.imagePullPolicy` | `IfNotPresent`                       | Image pull policy                                                          |
| `mattermost.siteName`              | _(unset)_                            | Overrides `MM_TEAMSETTINGS_SITENAME` (Mattermost default: "Mattermost")    |
| `mattermost.siteDescription`       | _(unset)_                            | Overrides `MM_TEAMSETTINGS_CUSTOMDESCRIPTIONTEXT` (shown above login form) |
| `mattermost.ingress.className`     | `traefik`                            | Ingress class                                                              |
| `mattermost.ingress.path`          | `/`                                  | Ingress path                                                               |

### PostgreSQL Configuration

| Value                 | Default    | Description        |
|-----------------------|------------|--------------------|
| `postgresql.image`    | `postgres` | PostgreSQL image   |
| `postgresql.imageTag` | `18`       | PostgreSQL version |
| `postgresql.username` | `postgres` | Database username  |
| `postgresql.password` | `postgres` | Database password  |
| `postgresql.database` | `postgres` | Database name      |
| `postgresql.size`     | `10Gi`     | PVC storage size   |

### Connection String

Generated automatically from the PostgreSQL values:

```
postgres://postgres:postgres@{release-name}-postgresql:5432/postgres?sslmode=disable&connect_timeout=10
```

## Uninstalling

```bash
helm uninstall mattermost --namespace mattermost

# The PostgreSQL StatefulSet PVC is not deleted by
# helm uninstall (volumeClaimTemplates PVCs are retained
# by Kubernetes as a safety measure).
# Clean up manually if you want to discard the database:
kubectl delete pvc -n mattermost -l app=postgresql
```

## Limitations

- Single replica deployment only
- Fixed PostgreSQL credentials (postgres/postgres/postgres)
- No TLS termination (handled upstream by load balancer)
