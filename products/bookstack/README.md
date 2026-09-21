# BookStack — Freepod chart

A self-contained Helm chart for [BookStack](https://www.bookstackapp.com/), a
wiki that organizes documentation into shelves, books, chapters and pages. The
chart renders the entire deployment directly; its only dependency is Freepod's
own `ssh-sidecar` library chart (which provides read-only file access to the
uploads).

## What it deploys

| Component | Object(s) |
|-----------|-----------|
| BookStack (web) | Deployment `<release>-bookstack` (+ SSH sidecar, + wait-for-DB and setup inits), Service `:8080` |
| MySQL | Deployment `<release>-mysql` + PVC `mysql-data` + Service `:3306` |
| Uploads | PVC `uploads` (plan-sized): `public/` at `public/uploads` (images), `storage/` at `storage/uploads` (attachments) |
| Credentials | Secret `<release>-db` (database, `APP_KEY`), Secret `<release>-admin` (first-start owner password, standalone installs only) |
| Ingress | `<release>-ingress` (per-deployment TLS via `caelus.ingress.tls`) |
| File access | Service `<release>-ssh` only (`ssh-sidecar`); session rooted at `volume:/uploads` |

**BookStack publishes no image of its own.** Its docs list two community
images; this chart runs `solidnerd/bookstack`, which runs as uid 33 from the
start, serves one Apache process on 8080, and takes its configuration from the
environment only (it moves any `.env` aside at start). The LinuxServer image
was the alternative: s6 as root, nginx, php-fpm, memcached and a queue worker
in one container, and a `.env` persisted on its volume beside the environment.

**The database is bundled** at the MySQL version upstream's reference compose
runs; BookStack speaks MySQL/MariaDB only, so the platform's PostgreSQL
relational storage cannot serve it. The server is tuned down from its
defaults (see `mysql.args` in `values.yaml`): untuned it idles at ~490Mi for a
database of a few megabytes, tuned it runs at ~135Mi with a 1Gi limit as
headroom.

`APP_KEY` is generated once and read back from `<release>-db` on every later
render: it encrypts stored MFA secrets, so a key that changed would lock
anyone using MFA out.

## The owner account

BookStack is multi-user, but every account shares one set of shelves and
books, with roles on top. A deployment therefore has one owner, and the tenant
is that owner: they sign in with their Freepod account's email
(`caelus.owner.email`) and the deploy dialog asks only for a display name
(`admin.name`) and a password.

The password is `BOOKSTACK_ADMIN_PASSWORD`, a required sensitive runtime var,
the same treatment as PhotoPrism's and Lemmy's admin passwords: encrypted at
rest, write-only through every API surface, and never in Helm values. BookStack
itself never reads it. The `setup` init container runs
`bookstack:create-admin --initial`, which rewrites the account BookStack's
migrations seed (`admin@admin.com` / `password`) with the owner's details.
Once any other admin exists it exits 2 and changes nothing, which the chart
treats as success, so later starts leave the owner's own edits in BookStack
alone.

A standalone `helm install` has no vars Secret, so the chart falls back to a
generated password in `<release>-admin`, emitted only in that case.

## Manual install

```bash
helm dependency build products/bookstack/chart
helm upgrade --install bookstack products/bookstack/chart \
  --namespace bookstack --create-namespace \
  --set host=wiki.example.com \
  --set admin.email=me@example.com \
  --set admin.password=choose-a-good-one
```

## Build and publish

Published to `oci://ghcr.io/erikvanzijst/freepod/charts/bookstack` by
[`scripts/publish-charts.sh`](../../scripts/publish-charts.sh), which CI runs on
every merge to `master`: bump `version` in `chart/Chart.yaml` and that version
is published. To publish by hand, from the repository root:

```bash
./scripts/publish-charts.sh bookstack
```

| Field               | Value                                                       |
|---------------------|-------------------------------------------------------------|
| Chart ref           | `oci://ghcr.io/erikvanzijst/freepod/charts/bookstack`       |
| Chart version       | `0.1.2`                                                     |
| User values schema  | see [`products/catalog/bookstack.yaml`](../catalog/bookstack.yaml) |
| Default Helm values | see [`products/catalog/bookstack.yaml`](../catalog/bookstack.yaml) |

## Upstream references

What a version upgrade has to review beyond the tag in
[`products/catalog/bookstack.yaml`](../catalog/bookstack.yaml), whose
`upstream` block detects new releases.

- **Release notes:** `https://www.bookstackapp.com/blog/` (one post per
  feature release, with upgrade notices) and the GitHub releases of
  `BookStackApp/BookStack`. The image's `26.5.5` is BookStack's `v26.05.5`.
- **Reference deployment:** `docker-compose.yml` in `solidnerd/docker-bookstack`.
  **The MySQL tag there is the one `mysql.image.tag` tracks**, whatever
  release track it is on; their Renovate bot moves it.
- **Runtime image:** `Dockerfile`, `docker-entrypoint.sh` and `php.ini` in
  `solidnerd/docker-bookstack`: the uid, the port, the required environment,
  the migrate-at-start, and the PHP upload cap.
- **Application configuration:** `.env.example.complete` in BookStack's own
  repository lists every environment option; `app/Config/setting-defaults.php`
  shows which settings are UI-stored rather than environment-driven.
- **Requirements:** `https://www.bookstackapp.com/docs/admin/installation/`
  (PHP and MySQL/MariaDB minimums).

Pitfalls:

- **Rebuild tags are excluded.** The image occasionally republishes a release
  as `X.Y.Z-N` (e.g. `26.3.4-1`) to fix its own packaging; the catalog `match`
  skips those, so such a fix arrives with the next plain release.
- **Uploads above 10M fail.** The image's `php.ini` caps
  `upload_max_filesize`/`post_max_size` at 10M while BookStack defaults to 50;
  `uploadLimitMB` keeps BookStack's own limit at 10 so the UI states the real
  one. Check `php.ini` on each upgrade.
- **`create-admin` exit codes are part of the contract.** The setup script
  treats 0 and 2 as success. If upstream renumbers them, first starts fail or,
  worse, later starts rewrite the owner's account.
- **The upload subdirectories are fixed.** `public/` and `storage/` on the
  `uploads` volume are what the two subPath mounts and the SFTP session see;
  renaming them orphans existing uploads.
- **Keep sessions in the database.** The image's file driver keeps them in
  the container filesystem, so every restart would sign everyone out.
