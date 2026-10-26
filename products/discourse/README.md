# Discourse — Freepod chart

A self-contained Helm chart for [Discourse](https://www.discourse.org/), a
discussion forum with chat. The chart renders the entire deployment directly;
its only dependency is Freepod's own `ssh-sidecar` library chart (which
provides read-only file access to uploads and backups).

## What it deploys

| Component                                                | Object(s)                                                                                                                                          |
|----------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------|
| Discourse (Pitchfork web server, Sidekiq forked from it) | Deployment `<release>-discourse` (+ SSH sidecar), init container `setup`; Service `:3000`                                                          |
| PostgreSQL 18 with pgvector                              | StatefulSet `<release>-postgres` + PVC `postgres-data` + Service `:5432`                                                                           |
| Redis (Sidekiq queues, message bus, cache)               | StatefulSet `<release>-redis` + PVC `redis-data` + Service `:6379`                                                                                 |
| Files                                                    | PVC `shared` (plan-sized) at `/shared`: `uploads/`, `backups/`, `tmp/`                                                                             |
| Credentials                                              | Secret `<release>-db` (database, `DISCOURSE_SECRET_KEY_BASE`), Secret `<release>-admin` (first-start owner password, standalone installs only)     |
| Owner seed                                               | ConfigMap `<release>-seed` (`seed_owner.rb`)                                                                                                       |
| Ingress                                                  | `<release>-ingress`, plus `<release>-uploads` (upload endpoints) and `<release>-static` (hashed static paths); Traefik middlewares `<release>-strip-accel`, `<release>-buffer-uploads` and `<release>-cache-static` |
| File access                                              | Service `<release>-ssh` only (`ssh-sidecar`); session rooted at `volume:/shared`                                                                   |

The images are upstream's own: `discourse/discourse`, the `web_only` image
built by `discourse_docker`, on the extended support release (ESR) track, and
`discourse/postgres`, which creates the `discourse` role and the `hstore`,
`pg_trgm` and `vector` extensions on first start. Redis is bundled at the
major version upstream's standard install runs. Upstream rebuilds an ESR's
image tag nightly, so the catalog pins it with a digest.

Every pod sets `hostUsers: false` and prefers the `nodePool` the catalog names,
the same way App Studio and `custom` do. The pool is preferred, not required,
so all three pods fall back to any node together; their `local-path` volumes
are created wherever the pods first land.

Deviations from upstream's packaging, each forced by the platform or chosen
for memory:

- **No runit, nginx or cron.** The image boots runit as root to supervise
  nginx, cron and the application server. The chart runs the application
  server alone, as `discourse` (uid 1000), with `DISCOURSE_SERVE_STATIC_ASSETS`
  so Rails serves the static files nginx would. Logs go to stdout
  (`RAILS_LOG_TO_STDOUT`) rather than files under `/shared/log`.
- **Pitchfork is exec'd directly**, not through `config/unicorn_launcher`, a
  supervisor script that ignores SIGTERM as PID 1. jemalloc is preloaded and
  transparent huge pages are off, as upstream's run script does.
- **One Pitchfork worker and one Sidekiq** (`web.workers`, `web.sidekiqs`),
  where upstream defaults to three workers. Each worker serves one request at a
  time.
- **Migrations and the owner seed run in an init container** (`setup`), not
  on boot in the application container (`MIGRATE_ON_BOOT`). Asset
  precompilation stays in the application container (`PRECOMPILE_ON_BOOT`,
  about ten seconds): the image ships no compiled assets, and precompiling
  writes outside `public/assets`.
- **Traefik stands in for nginx at the edge.** `strip-accel` removes a
  client's `X-Accel-Mapping` header on every route: Discourse (Rack 2) honors
  it and would answer with an empty body and an internal `X-Accel-Redirect`
  path that only nginx resolves. `buffer-uploads` buffers request bodies on
  `/uploads.json` and `/admin/backups/upload` only, so a slow upload never
  holds the single worker, which Pitchfork kills after 30 seconds. Everything
  else stays unbuffered, because the message bus streams its long-poll
  responses.
  `cache-static` adds the year-long immutable `Cache-Control` upstream's nginx
  sets on `/assets/`, `/plugins/` and `/images/emoji/`, which Rails omits.
- **Higher per-IP request limits** (`rateLimit`: 150 per 10 seconds, 400 per
  minute, where upstream has 50 and 200). Discourse's global limiter counts
  every request that reaches Rails and refunds only controller-served assets;
  behind nginx the static files never reach it, here they do, about 45 on a
  cold page load, which at upstream's limits turns a first sign-in into a 429.
  Discourse's own limits on logins, posting and the API are unchanged.

`DISCOURSE_SECRET_KEY_BASE` is generated once and read back from
`<release>-db` on every later render. Discourse accepts only 128 lowercase hex
digits and silently replaces anything else with a key it keeps in Redis.

## The owner account

Discourse is multi-user with staff roles. The deployment's owner is its
administrator: they sign in with their Freepod account's email
(`caelus.owner.email`), and the deploy dialog asks only for a display name
(`admin.name`, from which Discourse suggests the username) and a password.

The password is `DISCOURSE_ADMIN_PASSWORD`, a required sensitive runtime var.
The `setup` init container runs `seed_owner.rb` with `rails runner` after
migrating: unless an admin exists, it creates the owner as an active admin
with a confirmed email. The user is saved as an admin, so Discourse applies its
admin password rules (`min_admin_password_length`, 15), which the catalog's
`values_schema` mirrors, together with its common-password and
unique-character checks, which it cannot; a rejected password fails the init
container with Discourse's reason. The web server never starts on an instance
without an owner, so Discourse's first-run "register admin account" page is
never reachable.

A standalone `helm install` has no vars Secret, so the chart falls back to a
generated password in `<release>-admin`, emitted only in that case.

## What the tenant can change

A `DISCOURSE_<NAME>` variable whose name is a site setting pins that setting
and hides it from the admin UI. The chart pins `force_https` and
`notification_email` that way, and sets the hostname, database, Redis and SMTP
through Discourse's global settings, which the admin UI does not show.

Discourse's admin UI cannot install plugins; the image's bundled plugins are
fixed. What stays in the tenant's hands, none of which affects the
deployment's integrity: themes and theme components (installed from Git URLs
the tenant chooses), login methods, external storage for uploads and backups,
POP3 polling of an external mailbox, Discourse AI and its LLM credentials,
webhooks and the API. Those that make outbound requests are subject to the
tenant network policy.

Backups are written to `/shared/backups`, on the same volume as the data they
copy, and count toward the plan's storage. They are the tenant's export and
self-service restore, not the platform's backup. Upstream backs up weekly
with uploads, keeping five; the owner seed sets `backup_frequency` to 0 on
first start, so nothing is backed up automatically until the tenant schedules
it. It is set once rather than pinned, so that choice stays theirs.

Changing `host` after posts exist leaves absolute links in them pointing at the
old address; upstream's remedy is `rake posts:rebake`, which the chart does not
run.

## Manual install

```bash
helm dependency build products/discourse/chart
helm upgrade --install discourse products/discourse/chart \
  --namespace discourse --create-namespace \
  --set host=forum.example.com \
  --set admin.email=me@example.com \
  --set admin.password='choose-a-good-long-one'
```

## Build and publish

Published to `oci://ghcr.io/erikvanzijst/freepod/charts/discourse` by
[`scripts/publish-charts.sh`](../../scripts/publish-charts.sh), which CI runs on
every merge to `master`: bump `version` in `chart/Chart.yaml` and that version
is published. To publish by hand, from the repository root:

```bash
./scripts/publish-charts.sh discourse
```

| Field               | Value                                                              |
|---------------------|--------------------------------------------------------------------|
| Chart ref           | `oci://ghcr.io/erikvanzijst/freepod/charts/discourse`              |
| User values schema  | see [`products/catalog/discourse/discourse.yaml`](../catalog/discourse/discourse.yaml) |
| Default Helm values | see [`products/catalog/discourse/discourse.yaml`](../catalog/discourse/discourse.yaml) |

## Upstream references

What a version upgrade has to review beyond the tag in
[`products/catalog/discourse/discourse.yaml`](../catalog/discourse/discourse.yaml),
whose `upstream` block detects new releases.

- **Release notes:** <https://releases.discourse.org>, one changelog per
  version (`/changelog/v<version>`), with ESR support dates on the front page
  and an RSS feed at `/feed.xml`. Larger releases are announced on
  <https://meta.discourse.org> under Announcements.
- **Reference deployment:** `discourse/discourse_docker`:
  `.github/workflows/build-web-only.yml` (how the image is built and tagged:
  ESR versions plain, monthly releases with `-latest`), `samples/web_only.yml`,
  and `templates/web.template.yml` (the application server's run script:
  `MIGRATE_ON_BOOT`, `PRECOMPILE_ON_BOOT`, `RUBY_ALLOCATOR`, `UNICORN_*`, which
  the chart reproduces), `templates/postgres.template.yml` (the PostgreSQL
  major and the extensions) and `image/base/Dockerfile` (the Redis package and
  the PostgreSQL client).
- **Runtime image:** `config/pitchfork.conf.rb` in `discourse/discourse`
  (workers, bind address, the 30-second timeout, Sidekiq forking) and
  `config/environments/production.rb` (static files, `X-Accel-Redirect`).
- **Application configuration:** `config/discourse_defaults.conf` lists the
  global settings, each read from `DISCOURSE_<NAME>`; `config/site_settings.yml`
  lists the site settings an environment variable of the same name pins.
- **Owner seeding:** `lib/validators/user_password_validator.rb` (the admin
  password rules the `values_schema` mirrors).

Pitfalls:

- **Stay on the ESR track.** A Discourse site cannot move back from the monthly
  `-latest` releases to an ESR. The catalog's `match` excludes them.
- **A PostgreSQL major bump is a dump and restore**, not a tag change;
  `discourse/postgres` carries an `upgrade-postgres.sh` for it.
- **The `discourse/discourse` image is experimental upstream**: Discourse
  supports only its launcher-built installs. Check Meta for changes to how the
  image is built before an upgrade.
- **Upstream may switch the application server.** Discourse moved from unicorn
  to Pitchfork without renaming the `UNICORN_*` variables or
  `config/unicorn_launcher`; check `web.template.yml`'s run script on every
  upgrade.
