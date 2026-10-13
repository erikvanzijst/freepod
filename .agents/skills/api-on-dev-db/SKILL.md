---
name: api-on-dev-db
description: Run the local API (port 8000, behind the Vite dev server) against the dev cluster's platform database, so the local UI shows real dev data and its actions take effect on dev. Use when UI work needs real deployments, statuses or installs that the local container cannot produce (it has no reconciler and no cluster to deploy into). Dev only, never production.
---

# Run the local API against the dev database

The devcontainer's API normally uses the local Postgres, where nothing ever
reconciles: deployments stay `provisioning`, installs go nowhere. Pointing the
local API at dev's platform database gives the local UI dev's real data, and
the dev cluster's workers act on whatever it writes.

## Safety

- **Dev only.** The kubectl context in this container also reaches production
  (`caelus`). Everything here pins `-n caelus-dev`; never adapt it to another
  namespace.
- **Actions are real on dev.** An install creates a deployment the dev worker
  provisions, a removal deletes one, a paid plan starts a Mollie test payment.
  Other people's dev data is in the same database.
- **No migrations.** The API does not migrate on startup, and nothing here runs
  `alembic upgrade`. The launcher refuses to start when dev's schema revision
  differs from this checkout's head.

## Run it

Stop any API already on port 8000, then from the repo root:

```bash
.agents/skills/api-on-dev-db/run-api-on-dev-db.sh
```

Run it in the background; it stays in the foreground serving requests, with
uvicorn's reload watching `api/`. The UI dev server (`ui/`, port 5173) needs no
change: it proxies `/api` to port 8000 either way.

The launcher:

1. Port-forwards `caelus-dev/caelus-postgres` to `localhost:15432` unless
   something already listens there (override with `DEV_DB_PORT`), and stops
   that forward when it exits.
2. Compares dev's `alembic_version` with the checkout's head
   (`ALLOW_SCHEMA_MISMATCH=1` to start anyway).
3. Copies dev's static volume (icons, screenshots) to `var/dev-static` the first
   time (`REFRESH_STATIC=1` to copy again). Files are content-addressed, so a
   snapshot stays valid; new uploads made through dev appear only after a refresh.
4. Exports every `CAELUS_*` key of the `caelus-api-config` ConfigMap and
   `CAELUS_VAR_ENCRYPTION_KEYS` from the `caelus-var-keys` Secret. Without dev's
   keyring the API refuses to serve: it checks on startup that it can decrypt
   the stored vars.
5. Overrides what must be local: `CAELUS_DATABASE_URL` (the forward, with the
   `caelus-db` Secret's credentials), `CAELUS_STATIC_PATH`, `CAELUS_BASE_URL`,
   `CAELUS_BASE_URL_API`, and `CAELUS_MOLLIE_REDIRECT_URL` (so checkout returns
   to `localhost:5173`; Mollie's webhook still reaches dev's API, which shares
   the database).

Exported variables take precedence over `api/.env` and `api/.env.local`, so the
local defaults there don't leak in.

Check it with `curl -s localhost:8000/api/me -H 'X-Auth-Request-Email: <email>'`.
The local UI sends the email saved in the browser's `caelus.auth.headers`
localStorage entry, and the dev user with that email is who you are.

## What doesn't work locally

The ConfigMap's in-cluster addresses don't resolve here, so features that call
them fail from the local API: deployment logs (Loki), anything reading
Prometheus or OpenCost directly, and app-auth verification. The S3, DNS and
registry Secrets are not loaded, so artifact uploads (`freepod deploy`), custom
domain DNS and registry tokens don't work either. Use dev itself for those.

## Stop or switch back

Stop the launcher (it stops the port forward it started). Run the API the usual
way (`cd api && uv run python3 app/main.py`) to go back to the local database.
