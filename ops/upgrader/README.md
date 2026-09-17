# upgrader — the product upgrade service

Runs the [upgrade-product skill](../../products/UPGRADING/SKILL.md) for every
curated product, nightly, and keeps a browsable history of what it did. One
container serves the dashboard and executes runs on a background thread. It is
an ordinary Freepod `custom` deployment on the owner's account, not a platform
component.

Spec:
[product-upgrade-service](../../openspec/specs/product-upgrade-service/spec.md),
[product-upgrade-runs](../../openspec/specs/product-upgrade-runs/spec.md),
[product-upgrade-history](../../openspec/specs/product-upgrade-history/spec.md),
[product-upgrade-dashboard](../../openspec/specs/product-upgrade-dashboard/spec.md),
[product-upgrade-guardrails](../../openspec/specs/product-upgrade-guardrails/spec.md),
[product-upgrade-notifications](../../openspec/specs/product-upgrade-notifications/spec.md),
[product-upgrade-skill](../../openspec/specs/product-upgrade-skill/spec.md)
· Rationale:
[product-upgrade-service](../../openspec/changes/archive/2026-09-17-product-upgrade-service/design.md)

## Layout

| Path                              |                                                                                                                                   |
|-----------------------------------|-----------------------------------------------------------------------------------------------------------------------------------|
| `upgrader/`                       | the service: `web.py` (dashboard), `scheduler.py`, `runner.py` (per-product execution), `github.py`, `pi.py`, `store.py`, `db.py` |
| `migrations/`                     | Alembic, applied at container start                                                                                               |
| `bin/gh`, `bin/git`, `bin/docker` | the guards, first on a session's `PATH`                                                                                           |
| `hooks/pre-push`                  | installed through the system `core.hooksPath`                                                                                     |
| `upgrade_products.sh`             | the local runner                                                                                                                  |
| `Dockerfile`                      | the image; pins node, pi, `gh`, `helm`, python, `uv`, `jq`, `curl`, `tini`                                                        |
| `.freepod.json`                   | the deployment every `freepod deploy` from here updates                                                                           |

The image carries neither the skill nor the catalog: each product session reads
both from its own fresh clone of `master`. `PI_VERSION` in the `Dockerfile` is
kept in sync with `.devcontainer/Dockerfile`.

## Running locally

Tests:

```sh
uv sync
uv run pytest
```

Needs a reachable PostgreSQL. `UPGRADER_TEST_DATABASE_URL` is set for you inside
the devcontainer; outside it, point it at a server whose user holds `CREATEDB` —
the suite creates and migrates the database itself.

The local runner, the skill once per product in a fresh pi session and clone,
behind the same guards:

```sh
./upgrade_products.sh                 # every eligible product
./upgrade_products.sh vaultwarden     # one
```

Env: `MODEL`, `THINKING`, `UPGRADE_DRY_RUN` (default `1`), `UPGRADE_OUT_DIR`,
`REPO_URL`. Products run one after another: the inference backend serves a
single session at a time.

## Deploying

```sh
freepod deploy      # from ops/upgrader/
```

Builds `Dockerfile`, uploads this directory only, and rolls the deployment named
in `.freepod.json` (`upgrader.prutser.freepod.eu`). Migrations run before the
server binds. Nothing in CI builds or publishes this image; `uv run pytest` runs
in CI as the `upgrader-test` job.

Deploy and change vars **outside the nightly window**: a rollout marks an active
run `interrupted`, and the next night repeats it.

## Configuration

Everything arrives as deployment vars.

| Var                       | Default                          |                                                                        |
|---------------------------|----------------------------------|------------------------------------------------------------------------|
| `INFERENCE_BASE_URL`      | *required*                       | the inference endpoint                                                 |
| `INFERENCE_MODEL`         | *required*                       | the model id                                                           |
| `INFERENCE_API_KEY`       | *required*, **secret**           |                                                                        |
| `GITHUB_APP_ID`           | *required*                       | the installation is looked up from the repository, never configured    |
| `GITHUB_APP_PRIVATE_KEY`  | *required*, **secret**           | base64 of the PEM, on one line                                         |
| `DASHBOARD_PASSWORD`      | **secret**                       | unset refuses every page but `/healthz`                                |
| `UPGRADE_DRY_RUN`         | `1`                              | only `0` means real pull requests                                      |
| `THINKING_LEVEL`          | `medium`                         | `off`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`              |
| `SCHEDULE_TIME`           | `03:00`                          | `HH:MM` local, or `off`                                                |
| `SCHEDULE_TIMEZONE`       | `Europe/Brussels`                | an IANA zone                                                           |
| `PRODUCT_TIMEOUT_MINUTES` | `90`                             | per product, not per run                                               |
| `NOTIFY_EMAIL`            | unset                            | unset sends no email                                                   |
| `NOTIFY_FROM`             | `upgrader@freepod.eu`            |                                                                        |
| `SMTP_HOST`               | `smtp.mailer.svc.cluster.local`  | the cluster relay, which needs no credentials                          |
| `DASHBOARD_URL`           | unset                            | unset leaves emails and PR descriptions without a run link             |
| `REPO_URL`                | this repository                  | what each product clones; a local fixture for a scenario               |

`PORT`, `DATABASE_URL`, `BUCKET_NAME` and the `AWS_`, `S3_` and `PG` names come
from the platform and are read as they are.

```sh
freepod var set GITHUB_APP_PRIVATE_KEY --secret --stage    # prompts, no echo
freepod var set INFERENCE_BASE_URL=... INFERENCE_MODEL=... GITHUB_APP_ID=...
freepod var list
```

A missing required var does not stop the service: the run's products are
recorded `failed` naming the var, and the dashboard stays up.

## Operations

**Dashboard.** HTTP Basic, any username, `DASHBOARD_PASSWORD`. `/healthz` is
open. It lists runs, streams the running session, shows each product's files and
each PR's GitHub state, and carries "Run now", "Run one product" and cancel.

**Dry run ↔ real PRs.** The service ships dry: read-only tokens, guards refusing
writes, and the would-be PRs on the dashboard.

```sh
freepod var set UPGRADE_DRY_RUN=0     # real pull requests
freepod var set UPGRADE_DRY_RUN=1     # back to dry
```

**Reading a run.** `/runs/<id>`. Each product keeps `session.jsonl`,
`session.html`, `stdout.txt`, `result.json`, `body.md` and `change.patch` in the
deployment's bucket under `runs/<run-id>/<slug>/`, served over signed links that
expire in an hour. Secret values are redacted before anything is stored. Nothing
is pruned.

**A product stuck behind a leftover branch.** An interrupted real run can leave
an `upgrade/*` branch with no PR; the skill's duplicate check then skips that
product every night, with the reason on the dashboard. Delete the branch and
re-run the product:

```sh
git push origin --delete upgrade/<slug>-<target>
```

**Rotating the App's private key.** Generate a new key in the GitHub App's
settings, then repoint the var and delete the old key at GitHub. The bare key
name prompts without echo; paste `base64 -w0` of the PEM, never pass it on the
command line:

```sh
freepod var set GITHUB_APP_PRIVATE_KEY --secret
```

Suspending the App's installation revokes its access at once, without a deploy.

**Logs and a shell.** `freepod log -f`, `freepod shell`. The guards are on a
session's `PATH`, not on the shell's: probe them at `/app/bin/gh`,
`/app/bin/git`.
