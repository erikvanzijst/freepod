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
| App secrets | Secret `<release>-app` (admin username + SMTP); Secret `<release>-admin` (generated admin password, standalone installs only — see [Admin password](#admin-password))                                                                                                                                                                                                                                                                                         |
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

`image.tag` defaults to `<appVersion>-apache`. Set the `smtp.*` values for a
real deployment (defaults are dev-only). The `admin` password is generated on
first install; read it back with:

```bash
kubectl -n nextcloud get secret nextcloud-admin \
  -o jsonpath='{.data.NEXTCLOUD_ADMIN_PASSWORD}' | base64 -d
```

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
| Chart version       | `template.chart_version` in [`products/catalog/nextcloud.yaml`](../catalog/nextcloud.yaml) |
| User values schema  | see [User values schema](#user-values-schema) below                                 |
| Default Helm values | see [Default values (system_values_json)](#default-values-system_values_json) below |

## User values schema

Defines the form fields on the user-facing deployment dialog; the schema itself
is `template.values_schema` in
[`products/catalog/nextcloud.yaml`](../catalog/nextcloud.yaml). Everything else
(images, storage sizing, DB credentials, SMTP, TLS) is operator- or
plan-controlled and is not exposed. The tenant chooses two things: the hostname
and the admin password.

### Admin password

The tenant signs in as `admin` (`system_values.admin.username`) with a password
they choose in the dialog. It is `NEXTCLOUD_ADMIN_PASSWORD`, marked
`x-caelus-target: runtime`, `x-caelus-sensitive: true` and `required` — the same
treatment as BookStack's, Lemmy's and PhotoPrism's admin passwords — so it is
encrypted at rest, write-only through every API surface, and never enters Helm
values. The chart reads the vars Secret with `envFrom`, ahead of `<release>-db`
and `<release>-config`, so no var can displace a credential or the config.

The image reads it only on first start, when it runs `occ maintenance:install
--admin-pass "$NEXTCLOUD_ADMIN_PASSWORD"`, and ignores it afterwards; the admin
changes it in Nextcloud itself (Personal settings → Security). Two constraints
follow from that command and from Nextcloud's own `password_policy` app:

- `minLength: 10` matches the app's default minimum. The install itself runs
  before the app is enabled and would accept less, but the admin could then
  never change it to anything as short.
- A leading hyphen is refused: Symfony console reads `--admin-pass -x…` as a
  missing value and the first install fails, crash-looping the pod.

A standalone `helm install` has no vars Secret, so the chart falls back to a
generated password in `<release>-admin` (or `admin.password` when set). That
Secret is emitted **only** in the standalone case.

**Deployments created before chart 0.2.7** were installed with the template's
shared default password and hold no `NEXTCLOUD_ADMIN_PASSWORD` var. A tenant's
Edit stays on the deployment's own template, which does not declare the var, so
editing is unaffected. Moving one to a template that requires it is an
administrator action, and the platform validates the move against the new
template's `required`: the administrator must type a value, which is stored but
has no effect, because Nextcloud is already installed. It does not change the
password either; the shared default stays in place until an operator resets it
with `occ user:resetpassword admin`.

## Default values (system_values_json)

The admin configures a static default-values blob (`system_values_json`) on the
product template. It is merged over the chart's `values.yaml` for every
deployment created from that template, and is where operator-wide settings live —
SMTP, the admin account's username, and a pinned image tag. It is not where
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
`admin.username` names the first-run admin account. Its password is never a
system value: each tenant supplies their own (see [Admin password](#admin-password)).

## Upstream references

What a version upgrade has to review beyond the tag in
[`products/catalog/nextcloud.yaml`](../catalog/nextcloud.yaml), whose `upstream`
block detects new releases.

- **Release notes:** the `nextcloud/server` GitHub releases are only one-line
  pointers. The changelog is on the `nextcloud-releases/server` release with the
  same tag (`vX.Y.Z`).
- **Image source:** `nextcloud/docker`, directory `<major>/apache/`
  (`Dockerfile`, `entrypoint.sh`, `cron.sh`, `upgrade.exclude`,
  `config/*.config.php`), which is generated from `Dockerfile-debian.template`
  and `docker-entrypoint.sh` at the repository root. That repository has no
  per-release tags. `git log -- <major>/apache/Dockerfile` lists the
  "Runs update.sh" commits that bump `NEXTCLOUD_VERSION`, so diff from the
  commit that bumped to the current version to the one that bumped to the
  target.
- **Official chart:** `nextcloud/helm`, `charts/nextcloud`. Its `appVersion`
  names the release a chart version targets, and it can lag behind the image.
- **Major versions:** critical changes are listed at
  `https://docs.nextcloud.com/server/<major>/admin_manual/release_notes/upgrade_to_<major>.html`,
  and requirements (PHP, databases) at
  `https://docs.nextcloud.com/server/<major>/admin_manual/installation/system_requirements.html`.

Pitfalls:

- Nextcloud upgrades one major version at a time. An instance can't skip a
  major, and must be on the latest patch release of its current major before
  moving to the next (for example 32.0.6 → 32.0.15 → 33.x).
- The bundled PostgreSQL (`postgres:17-alpine`) doesn't follow Nextcloud's
  version. On a new major, check its supported database versions against it.
- The image's `config/*.config.php` files (S3, Swift, Redis, SMTP, …) only take
  effect when their environment variables are set. Check which ones this chart
  sets (`templates/configmap.yaml`) before calling a change to one of them not
  applicable.
- The `before-starting` hook (§ What it deploys) runs the post-upgrade repair
  steps. If upstream starts recommending a new one after upgrades, it belongs
  there.
