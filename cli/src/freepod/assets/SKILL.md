---
name: deploy-to-freepod
description: Deploy a web app to freepod.eu using the `freepod` CLI — it builds a container from source with no Dockerfile and serves it on its own HTTPS hostname. Use when asked to deploy, ship, host, or put a web app online; when adapting an existing codebase to run on Freepod; or when the user mentions freepod, `freepod deploy`, or `.freepod.json`. Also read it *before* designing a new app that will be deployed there, because the platform's constraints (bind `$PORT`, no disk, one HTTP process) decide whether an app can run at all.
---

# Deploying to Freepod

Freepod takes a source directory, builds it into a container image, and serves
it at a hostname over HTTPS. No Dockerfile is required — [Railpack](https://railpack.com)
detects the stack — but a project that has one is built from it instead, so read
*Which builder runs* before deploying a repository that ships a Dockerfile. The
whole workflow is:

```bash
freepod login      # once, interactive — a human has to do this
freepod init       # choose a hostname, writes .freepod.json
freepod deploy     # pack, upload, build, release
```

Deployment is not the hard part. **Fitting the platform's constraints is**, and
they are strict enough to rule some applications out entirely. Read the next
section before you write or port any code.

## Does the app fit? Check before writing code

Five constraints. Each one silently produces a deployment that builds fine and
then does not work.

**1. The app must bind `0.0.0.0:$PORT`.** The platform assigns the port and
passes it in the environment. An app that hardcodes a port receives no traffic.
Read it as `process.env.PORT`, `os.environ["PORT"]`, `os.Getenv("PORT")` —
whatever your language spells it — and bind `0.0.0.0`, never `127.0.0.1`.

**2. There is no persistent disk.** Anything the app writes to its own
filesystem is gone at the next restart and at every release. This rules out
SQLite, local file uploads, on-disk session stores, and any cache whose loss
matters.

**3. There is a PostgreSQL database, and nothing else.** Every deployment gets
its own database (below) and its own private S3 bucket (below). There is no
MySQL, no Redis, and no way to run one — anything that would be a second process
is ruled out by constraint 5. An app that needs a cache or a queue must either
use the database for it or drop the requirement.

**4. Runtime configuration goes through `freepod var`, not through files.**
An app that needs an API key at request time reads it from the environment, and
you put it there with `freepod var set`:

```bash
freepod var set LOG_LEVEL=debug          # sets it and rolls the deployment
freepod var set STRIPE_KEY --secret      # prompts without echo; write-only
freepod var list                         # secrets show as <hidden>
```

Setting a var rolls the deployment, because that is what makes it take effect.
Several in one command produce one rollout, and `--stage` records them for the
next deploy instead.

These reach the *running* container only. A variable the build itself has to
read goes in a `railpack.json` — see *Variables the build needs*.

**Never put a credential in a file you commit, and never hardcode one.** Ask
the user to run `freepod var set KEY --secret` themselves — a value passed as
`KEY=value` on a command line is in the shell history, and a value you write
into the repository is in the registry image forever. A var marked `--secret`
is write-only: the platform never returns it, so nothing — not the CLI, not
you — can read it back.

Some names are reserved because the platform sets them: `PORT`, the `AWS_*`
and `S3_*` object-storage credentials, `BUCKET_NAME`, and anything starting
with `CAELUS_` or `RAILPACK_`. `freepod var set` refuses them.

`DATABASE_URL` and the `PG*` variables are **not** refused today, but setting
one achieves nothing: the platform's own values are applied after your vars, so
yours is silently overridden. Never set them.

**5. One HTTP service per deployment.** No sidecars, no worker processes, no
scheduled jobs. If the app is a stack of cooperating services, only one of them
can live here.

If the app fails any of these and cannot be adapted, say so before building
anything. That is a more useful answer than a deployment that comes up broken.

## The database

Every deployment gets its **own PostgreSQL 18 database** and a role that owns
it. Nothing to provision, enable or configure — the credentials are already in
the environment:

```
DATABASE_URL                 postgresql://<role>:<password>@<pooler>:6432/<db>
PGHOST  PGPORT  PGUSER  PGPASSWORD  PGDATABASE
```

`DATABASE_URL` is what an ORM or driver wants; the `PG*` variables are what
libpq, `psql` and `pg_dump` read with no arguments. **Read them from the
environment** — the database and role names are derived from the deployment's
id and are not guessable, and the password is rotated by the platform, not by
you.

```python
import os, psycopg
with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
    conn.execute("CREATE TABLE IF NOT EXISTS visits (id serial primary key)")
```

### What you own, and what you cannot do

You own the database: schemas, tables, indexes, and PostgreSQL's **trusted**
extensions (`pgcrypto`, `uuid-ossp`, `citext`, …) all work. You cannot create a
second database, install untrusted extensions (anything needing superuser), or
reach another deployment's data — every tenant database has `CONNECT` revoked
from `PUBLIC`.

Three settings are applied to your role and re-applied on every deploy:

| Setting                               | Value | Can you change it? |
|---------------------------------------|-------|--------------------|
| `statement_timeout`                   | 30s   | yes, per session   |
| `idle_in_transaction_session_timeout` | 60s   | yes, per session   |
| `temp_file_limit`                     | 64MB  | **no**             |

A query killed at 30s is your own timeout, not a platform fault — raise it for
the session if a migration or a report legitimately needs longer.

Freepod does not support the following db session operations: `SET`,
`LISTEN`/`NOTIFY`, session-level advisory locks, `WITH HOLD` cursors, temporary tables

### Migrations

There is no release phase and no way to run a one-off command against the
database, so you'll need to run migrations run at startup, before the server binds.
E.g.:

```procfile
web: sh -c 'alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port $PORT'
```

### The size allowance

The plan bounds the database's size, and crossing the line changes what the
database will do:

| Usage     | quota_state | What your app sees                                              |
|-----------|-------------|-----------------------------------------------------------------|
| under 80% | ok          | nothing                                                         |
| 80%, 90%  | warned      | nothing — the account owner gets an email                       |
| **100%**  | readonly    | writes fail: `cannot execute INSERT in a read-only transaction` |
| **150%**  | blocked     | connections are refused entirely                                |

Falling back under the allowance reverses each step within about a minute.

Two things make the ceiling harder than it looks: deleting rows does not shrink
a table on its own, and a read-only database refuses `VACUUM` — so a full
database cannot be emptied out of trouble from inside. Treat the allowance as a
design constraint, and check usage from the app itself:

```sql
SELECT pg_size_pretty(pg_database_size(current_database()));
```

You can also check the current usage from the CLI with `freepod db status`.

### Backups

There are none you can reach — no snapshot, no restore, no support request.
An accidental `DROP TABLE` is gone. If the data matters, export it to the
deployment's bucket on a schedule you control. Deleting the deployment revokes
access immediately and destroys the data after a short retention period.

A one-off dump is available from your machine — `freepod db proxy` plus a local
`pg_dump` (see Debugging it).

### Debugging it

You can reach the database from your machine over the platform's SSH edge, with
one SSH key registered on your account (`freepod key add`) and `ssh` on your
PATH:

- `freepod shell <tool>` runs the platform's own PostgreSQL tools — `psql`,
  `pg_dump`, `pg_restore` — against your database and streams the result here.
  Nothing to install, no tunnel to hold. **This is the one to reach for.**
- `freepod db shell` opens an interactive `psql` session server-side. Same
  tools, driven by a human at a terminal rather than by you.
- `freepod db proxy` forwards a local port and prints a connection URL for the
  local end, for when the client has to be a local one — an IDE, a GUI, a tool
  that is not in the platform's toolbox.

`freepod log` is still the first move for *application* errors. These are the
errors worth recognizing:

| What you see                                               | What it means                                                                  |
|------------------------------------------------------------|--------------------------------------------------------------------------------|
| `cannot execute INSERT in a read-only transaction`         | you are at 100% of the allowance                                               |
| `bouncer config error` at connect                          | the role cannot log in — over 150%, or the deployment was deleted              |
| `connection was closed in the middle of operation`         | the server connection went away mid-query; retry, and check the two rows above |
| `password authentication failed`                           | you are not using `DATABASE_URL` / `PG*` from the environment                  |
| `permission denied to create database`                     | expected: you get exactly one                                                  |
| `must be superuser to create this extension`               | that extension is untrusted; only trusted ones are installable                 |
| `canceling statement due to statement timeout`             | your own 30s limit; raise it for that session if the work is legitimate        |
| rollout fails with *"plan declares no database allowance"* | a platform-side plan misconfiguration, not an app bug — report it              |

A one-off query needs neither a tunnel nor a local client: `freepod shell
"psql -Atc 'select count(*) from users'"` runs it in the platform's own client
and prints the result. (`freepod db shell` answers the same question
interactively, which is for a human at a terminal, not for you.) **Do not add REST
endpoints that print environment variables or the connection string** — they
would be on the public internet. Print what you need to the log instead, where
only you can read it.

The most likely first thing you reach for is a dump, and it is one command.
`pg_dump` runs in the platform's toolbox and streams to your standard output:

```bash
freepod shell pg_dump > backup.sql
freepod shell pg_dump -Fc > backup.dump   # custom format, for pg_restore
```

Restoring goes back the same way, over standard input:

```bash
freepod shell psql < backup.sql
freepod shell 'pg_restore -d "$PGDATABASE"' < backup.dump
```

Quote only what your own shell would otherwise act on: `$PGDATABASE` is set on
the far side, so it has to arrive unexpanded rather than being resolved here,
where it is empty. Plain flags such as `-Fc` need nothing — everything after
the first word is the remote command's.

Take the dump *before* anything destructive — a schema change you are unsure
of, a bulk delete, a migration you have not run against real data. It costs one
command, and there is no undo on the other side.

`freepod db proxy` is the fallback for a client that must run locally: hold the
tunnel in one terminal and point the local client at the URL it prints from
another.

```bash
# terminal 1 — prints the URL, holds the tunnel until Ctrl+C
freepod db proxy

# terminal 2 — a local client, against the URL terminal 1 printed
psql "postgresql://…@localhost:5432/<db>"
```

## Object storage: the other place state can live

Every deployment is also given its own **private S3 bucket** on the platform's
Garage instance — the right home for anything large or file-shaped, and for the
exports the database has no backups for. There is nothing to enable, provision,
or configure — the credentials are in the container's environment under the
names an S3 SDK already looks for:

```
AWS_ACCESS_KEY_ID          AWS_ENDPOINT_URL_S3     S3_BUCKET
AWS_SECRET_ACCESS_KEY      AWS_ENDPOINT_URL        BUCKET_NAME
AWS_REGION / AWS_DEFAULT_REGION
```

> **The bucket name is in `S3_BUCKET` (or its alias `BUCKET_NAME`), which is
> not an `AWS_*` variable and has no AWS convention behind it.** This is the
> single most guessable-wrong fact on this page. Everything else an SDK picks
> up on its own; the bucket name it cannot.

In Python that is the whole of it:

```python
import boto3, os
s3 = boto3.client("s3")                    # reads AWS_* from the environment
s3.put_object(Bucket=os.environ["S3_BUCKET"], Key="hello.txt", Body=b"hi")
```

Three things worth knowing:

- **Path-style addressing.** The endpoint serves `…/bucket/key`, not
  `bucket.host/key`. boto3 selects this automatically for a custom endpoint.
  The JavaScript v3 client does not: pass `forcePathStyle: true`.
- **Presigned URLs work in a browser.** The endpoint is publicly reachable, so
  a URL the app signs can go straight to an end user for download or upload,
  and the bytes never pass through the container. CORS is preconfigured,
  including the `ETag` exposure that multipart uploads need.
- **User metadata does not survive.** Garage does not return `Metadata` on
  `GetObject`. Use the object's `LastModified`, or store what you need in the
  object body or the key.

## Make the start command explicit

Railpack infers a start command from the source tree. The inference is good but
it is a guess, and a wrong guess costs a build cycle you cannot debug from
logs. Remove the guess with a `Procfile` at the project root — it takes
precedence, and it works whatever the language:

```procfile
web: <the command that starts your server, binding 0.0.0.0:$PORT>
```

```procfile
web: uvicorn main:app --host 0.0.0.0 --port $PORT      # Python / ASGI
web: gunicorn -b 0.0.0.0:$PORT app:app                 # Python / WSGI
web: node server.js                                    # Node
web: ./server                                          # compiled binary
```

Railpack still handles dependency installation from whatever manifest it finds
(`requirements.txt`, `pyproject.toml`, `package.json`, `go.mod`, `Cargo.toml`,
…). The `Procfile` only pins the last step.

## Which builder runs

A file named `Dockerfile` in the **project root** takes the build over. The
platform builds that Dockerfile and does not detect the stack. Anything else is
detected as before. The first line of the build log says which one ran.

There is no opt-out and no fallback: a Dockerfile that fails to build fails the
deploy. If a repository ships a Dockerfile you do not want used, rename it or
exclude it with `.freepodignore`.

What changes when the Dockerfile takes over:

- **`railpack.json` and `Procfile` stop applying.** They are Railpack's input,
  and Railpack did not run. Build variables declared there are not passed to
  the Dockerfile — bake the value into the Dockerfile itself.
- **The port contract does not change.** The image must still bind
  `0.0.0.0:$PORT`. A Dockerfile that hardcodes a port builds and deploys and
  then serves nothing; the build log warns when the image's declared ports do
  not include the platform's.
- **A `# syntax=` directive is ignored.** The platform pins the Dockerfile
  frontend, so a directive naming another one has no effect. Dockerfiles
  needing a syntax feature newer than the pinned frontend will fail.
- **`RUN --security=insecure` and `network=host` are unavailable** and fail
  with BuildKit's own error.
- **Base images are pulled from wherever the Dockerfile names them.** A Docker
  Hub base image is pulled anonymously and can hit that registry's rate limits.

Everything else is unchanged: the same size limit on the upload, the same
runtime constraints, and `freepod var` still supplies the running container's
environment.

## Variables the *build* needs

`freepod var` is runtime only: its values reach the running container and do
not exist while the image is being built. `freepod deploy` takes no build
flags. None of this applies to a project built from its own Dockerfile — see
*Which builder runs* — which is built with its own `ARG` defaults. So a project
whose *build* reads configuration — a Vite config branching
on `process.env.FEATURE`, a static site baking in an API base URL, anything you
would have passed to `docker build --build-arg` — needs one of two mechanisms:
`dotenv` files, or vars declared in `railpack.json`. They do not overlap, and
which one works is decided by how the code reads the  value, not by preference.

### Dotenv files

These are ordinary files in the source tree. Nothing on the platform reads
them; only your own tooling does. `.env` and `.env.<mode>` ship with the
upload, while `.env.local` and `.env.*.local` are excluded by default and never
leave your machine. Because `vite build` and `next build` run in production
mode, a committed `.env.production` is picked up on the platform and ignored by
your local dev server, with no `.local` file needed — the idiomatic way to give
a static site a different `API_BASE_URL` in production than in development.

Two things about them surprise people:

- **A dotenv file creates no environment variables.** Vite, for instance, maps
  only `VITE_`-prefixed entries into `import.meta.env` for the client bundle;
  inside `vite.config.ts`, `process.env.FOO` and even `process.env.VITE_FOO`
  are `undefined`. A build that reads `process.env` needs `railpack.json`.
- **A gitignored dotenv file never reaches the build**, with no warning, since
  the upload honors `.gitignore` and most projects ignore `.env`. Commit a
  `.env.production` rather than un-ignoring `.env`, which is local
  configuration and may hold credentials.

### `railpack.json`

A `railpack.json` at the project root puts real environment variables into the
build step's container, which is what `process.env` and `os.environ` read:

```json
{
  "$schema": "https://schema.railpack.com",
  "steps": { "build": { "variables": { "SIMPLE_MODE": "true" } } }
}
```

This merges with Railpack's detection rather than replacing it: the build step
keeps the command, inputs and caches it would have had, and gains the variable.

Two spellings look right and do nothing: a top-level `"variables"` or `"env"`
object is silently ignored — the variable has to sit under the step.

### Neither one takes a secret

A dotenv file is committed to your repository and compiled into the image; a
`railpack.json` is committed too. `freepod var set --secret` keeps a value out
of both, but it is runtime-only by design — the platform has no build-time
secret mechanism at all today. A build that genuinely needs a credential (a
private package registry token, say) cannot run on Freepod as-is. Say so rather
than committing the token.

## The procedure

### 1. Confirm authentication before anything else

```bash
freepod whoami
```

Exit code 3 means not authenticated. **Do not try to log in on the user's
behalf.** `freepod login` needs a human at a browser: in a container or over
SSH it falls back to the device flow, which prints a URL and a code that
someone has to approve on another device, and it blocks for up to 300 seconds
waiting. Stop and ask the user to run `freepod login` themselves.

### 2. Initialize the project

`freepod init` **prompts interactively** for a hostname. To run it
non-interactively, pipe the answer:

```bash
printf 'myapp\n' | freepod init
```

A bare label becomes a subdomain of the platform (`myapp` → `myapp.freepod.eu`).
A value containing a dot is taken as already qualified, for a custom domain
pointed at the platform with a CNAME. Certificates are issued either way.

This writes `.freepod.json`, which records the hostname and — after the first
deploy — the deployment this directory belongs to. It is meant to be committed.
To change a value, edit the file. Do not re-run `init --force` or
`deploy --recreate` on an initialized project unless the user asks: both
discard the deployment pointer and orphan the running deployment.

### 3. Verify locally — this step is not optional

**The platform offers no runtime logs.** There is no `freepod logs`. Once the
container is running, the only thing you can observe from outside is its HTTP
responses. Every bug you do not catch locally becomes a bug you diagnose by
redeploying.

So run the app the way the platform will, and exercise it:

```bash
PORT=8080 <your start command>
curl -sS localhost:8080/           # and every other route that matters
```

If the app talks to S3, stub the client locally rather than skipping the path
entirely — a fake in-memory S3 in a test is enough to prove routing,
serialization and error handling before a build is spent on it.

### 4. Deploy

```bash
freepod deploy
```

Preflight, pack, upload, build, release. **Allow several minutes** — builds
typically run one to three minutes and the client waits up to 1800s for the
build and 600s for the rollout, so set a generous timeout on whatever runs it.
The build log streams to stderr. Stdout carries exactly one line, the live
address:

```bash
URL=$(freepod deploy)
```

Ship a new version by running it again.

### 5. Verify the deployed app

Do not report success because `deploy` returned. Exercise the live URL the way
you exercised localhost — at minimum a health endpoint and the primary write
path, since the S3 wiring is the part that could not be fully tested locally.

Then read `freepod log`. An application can answer requests correctly and still
be logging a failure on every one of them, and the log is the only place that
shows. It is also the fastest way to see that a redeploy actually took effect.

## What gets uploaded

The working tree, minus `.git/`, minus your `.gitignore`, minus built-in
defaults that already cover the usual noise: `node_modules/`, `.venv/`,
`venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `target/`, `dist/`,
`build/`, `.DS_Store`, `*.swp`, `.env.local`, `.env.*.local`. You do not need
to re-exclude any of those.

Add a `.freepodignore` (same syntax as `.gitignore`, applied last) only for
things those rules miss. Two wrinkles:

- `dist/` and `build/` are excluded by default. If the project depends on a
  *committed* build output rather than building on the platform, re-include it
  explicitly or the image will be missing it.
- A negation must name the path: `!node_modules/patched.js` works, a bare
  `!patched.js` does nothing, and nothing under a directory you excluded
  yourself can come back — exclude `build/*` rather than `build/` if you need
  an exception.
- A gitignored file is absent from the build with no warning — `.env` is the
  common one, since almost every project ignores it. If a dotenv file is what
  the build reads, commit a `.env.production` rather than un-ignoring `.env`;
  see *Variables the build needs*.

## When it goes wrong

| Symptom                               | What it means                                   | What to do                                                                                                                                                                |
|---------------------------------------|-------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Exit 3                                | Not authenticated                               | Ask the user to run `freepod login`                                                                                                                                       |
| Exit 4, build log ends in an error    | Build failed                                    | The streamed log is the whole story; `freepod builds` lists status and duration                                                                                           |
| Exit 5                                | Image built, rollout failed or timed out        | Usually the container exits at startup — check the start command and that it binds `0.0.0.0:$PORT`. `freepod releases` shows which release failed and which is still live |
| Deploy succeeds, requests hang or 502 | App is not listening where the platform expects | `freepod log` — then bind `0.0.0.0:$PORT`, not a hardcoded port and not `127.0.0.1`                                                                                       |
| Deploy succeeds, one endpoint 500s    | A runtime fault                                 | `freepod log -f`, then exercise the failing request                                                                                                                       |
| Writes 500 but reads work             | The database is at 100% of its allowance        | `freepod log` shows `read-only transaction`; the exit is a larger allowance, not a delete — see The database                                                              |
| Every request 500s on a database call | Connections refused, or credentials not read    | `freepod log` — `bouncer config error` means the role cannot log in; `password authentication failed` means the app is not using `DATABASE_URL` from the environment      |
| Logs are clean but behavior is wrong  | What shipped may not be what you think          | `freepod shell ls -la /app` and `freepod shell env` — read the running container instead of theorizing about it                                                           |

**Read the logs first.** `freepod log` prints what the application wrote to
stdout and stderr. Reach for it before theorizing, before adding instrumentation,
and before redeploying — most runtime faults name themselves in a traceback that
is already there.

```bash
freepod log             # recent output, then exit
freepod log -f          # keep watching; then exercise the failing request
freepod log -r 4        # one release, including one that failed and was rolled back
```

`freepod releases` is where the number for `-r` comes from. It lists this
project's rollouts, most recent first, with the status of each, the image it
shipped, and a `*` on the one currently serving traffic:

```bash
freepod releases        # RELEASE  STATUS  CREATED  DURATION  IMAGE
```

The marked release is not always the newest one — a rollout that failed leaves
the previous release live — so this is also how you tell "my deploy failed and
the old version is still up" from "my deploy worked and the app is wrong",
which are different problems with the same symptom.

A failed deploy usually explains itself: `freepod deploy` already prints the tail
of the failed release's output alongside the platform's error, so a container
that died on startup tells you why without a second command. If you need more
than the tail, `freepod log -r <number>` reads that release in full — the lines
outlive the container, so a rollout that was rolled back is still readable.

Anything the app writes to stdout or stderr is captured, so print what you need
rather than building a way to fetch it. **Do not add a diagnostic HTTP endpoint
that reports environment variables or configuration** — it would be on the public
internet, and logs answer the same question privately.

Two things logs cannot tell you, because they are not the application's output:
whether the container is running at all, and what the platform did. For those,
`freepod deploy`'s own error and the deployment status are the record.

Give every app a `/healthz` from the start. It costs three lines and it
separates "the container is not running" from "the container is running and the
app is wrong."

### Reading the running container

`freepod shell` runs a command in the application container, the way `ssh host
<command>` does. **Always give it a command.** With none it opens an interactive
session, which you cannot drive — it will sit there holding the terminal.

```bash
freepod shell env                      # what the app actually got in its environment
freepod shell ls -la /app              # what the image shipped
freepod shell cat /app/config.yaml
freepod shell 'ps aux | head'          # quote a pipeline, or the local shell takes it
freepod shell "psql -Atc 'select 1'"   # a query, with no tunnel and no local client
```

It lands in the app's own working directory with the app's own environment, so
what it reports is what the app sees. The exit code is the command's — 127 for a
command the image does not carry — and its output is this terminal's, so
redirection and pipes work on both sides: `freepod shell cat /app/app.log >
local.log`, and `freepod shell psql < backup.sql` feeds it the other way. A
full-screen program needs a terminal, which `-t` allocates; nothing else does.

The PostgreSQL tools are the exception to "runs in the application container":
`psql`, `pg_dump`, `pg_restore` and `pg_isready` run in the platform's own
sidecar, against your database, whether or not your image carries a client — so
`freepod shell pg_dump > backup.sql` is a backup in one command. A deployment
with no database declines them by name rather than failing inside the tool.

This answers the questions logs cannot: which files actually shipped, which
environment variables actually arrived, whether the process is running at all.
It is **not** where you fix what you find. The container's filesystem is gone at
the next restart and at every release, so an edit made here is lost, invisible
to the next deploy, and a fix you cannot reproduce. Change the source and
redeploy.

It needs a registered key (`freepod key add`) and `ssh` on the PATH, like the
other SSH commands, and it reaches a container that is up even when the app
inside it is not.

### Copying files in and out

`freepod cp` moves a file or a whole directory either way. Mark the
deployment's side with a leading colon; the other side is local, and which one
is marked decides the direction.

```bash
freepod cp :/app/app.log ./app.log     # out, to read locally
freepod cp ./fixture.json :/app/       # in, for a one-off
freepod cp :/app/uploads ./uploads     # a tree, no recursion flag
```

Nothing needs to be installed in the image — the platform serves the transfer —
and a relative remote path means what it means in `freepod shell`. Directories
keep their structure and their files' modes; owners and timestamps do not
survive. Exactly one side must be marked: with neither or both it refuses
before connecting rather than guessing.

The same caveat as `freepod shell` applies with more force: **a file copied in
is gone at the next restart and at every release.** Use it to get data out, or
to try something for a moment, never to fix a deployment. Change the source and
redeploy.

## Command reference

| Command            | Purpose                                                                                                                                                              |
|--------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `freepod login`    | Sign in. Interactive — a human must do it.                                                                                                                           |
| `freepod whoami`   | Report the authenticated account. Never starts a login.                                                                                                              |
| `freepod init`     | Set up the directory; prompts for a hostname.                                                                                                                        |
| `freepod deploy`   | Pack, build, release. Prints the URL on stdout.                                                                                                                      |
| `freepod log`      | Read the application's output. `-f` follows, `-r N` pins one release, `-t` adds timestamps.                                                                          |
| `freepod shell`    | Run a command in the application container: `freepod shell env`. Always pass one — with no command it is interactive. Needs a registered key and `ssh`.              |
| `freepod cp`       | Copy a file or directory between here and the deployment: `freepod cp :/app/app.log ./app.log`. Mark the deployment's side with `:`; the direction follows. Needs a registered key and `sftp`. |
| `freepod builds`   | List this account's builds, most recent first.                                                                                                                       |
| `freepod releases` | List this project's rollouts, newest first, marking the live one. Where `log -r N` gets its N.                                                                       |
| `freepod var`      | Read and change the app's environment: `var list`, `var get KEY`, `var set KEY=VALUE`, `var rm KEY`. `--secret` stores write-only; `--stage` defers the rollout.     |
| `freepod delete`   | Delete the deployment **and everything it stores**. Destructive; confirm with the user first, and note it prompts unless given `-y`.                                 |
| `freepod db`       | Read this deployment's database: `db status` reports database name, role, password (masked by default; `--show-password` reveals), and quota state. No host, no URL. |
| `freepod db shell` | Open an interactive `psql` session server-side; no local PostgreSQL client needed. Needs a registered key and `ssh`.                                                 |
| `freepod db proxy` | Forward a local port to the database and print a connection URL for the local end; the tunnel runs until Ctrl+C. Needs a registered key and `ssh`.                   |
| `freepod key`      | Register the SSH keys that identify you: `key add` (generates one if you name no file), `key list`, `key rm <fingerprint>`. The prerequisite for the SSH commands.   |
| `freepod logout`   | Forget the cached credential.                                                                                                                                        |

Exit codes: `0` ok, `2` usage, `3` not authenticated, `4` build failed,
`5` rollout failed, `1` anything else.
