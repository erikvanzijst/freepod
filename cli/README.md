# freepod

Take a local project directory to a running deployment on
[freepod.eu](https://freepod.eu).

```bash
brew install erikvanzijst/tap/freepod     # Mac, Linux
uv tool install freepod                   # Mac, Linux, Windows
pip install freepod                       # Mac, Linux, Windows
```

```bash
cd myapp
freepod login      # sign in through the browser
freepod init       # choose a hostname for this project
freepod deploy     # https://myapp.freepod.eu
```

`deploy` packs the working tree, uploads it, builds a container image on the
platform and releases it. By the time the command returns, the app is live on
its own hostname over HTTPS. Ship a new version by running it again.

No Dockerfile to write and nothing to configure:
[Railpack](https://railpack.com) detects the stack — Node, Python, Go, Java,
PHP, Ruby, Rust and more — and builds an image from your source as it is. A
project that *does* have a `Dockerfile` in its root is built from that instead.

## What you need

- **A Freepod account.** `freepod login` opens the sign-in page, which is also
  where you can register.
- **Python 3.9 or newer**, or Homebrew. The project you deploy can be in
  any language Railpack supports.
- **An app that listens on `$PORT`.** The platform assigns the port and passes
  it in the environment, so bind `0.0.0.0:$PORT` (`process.env.PORT`,
  `os.environ["PORT"]`, …) rather than a fixed number. An app that picks its own
  port receives no traffic.
- **`ssh`, for the interactive commands.** `shell`, `db shell`, and `db proxy`
  drive the system `ssh` to reach the deployment over the platform's SSH edge;
  the client does not implement the protocol itself. Everything else — login,
  deploy, log, var, `db status` — needs no `ssh`.

## Commands

| Command            | What it does                                                                         |
|--------------------|--------------------------------------------------------------------------------------|
| `freepod login`    | Sign in, and remember the credential.                                                |
| `freepod init`     | Set the current directory up as a project: choose a hostname, write `.freepod.json`. |
| `freepod deploy`   | Pack, build and release the current project.                                         |
| `freepod var`      | Read and change the environment your application runs with.                          |
| `freepod log`      | Stream your application's pod output.                                                |
| `freepod shell`    | Open a shell in the deployment's application container, or run a command in it.      |
| `freepod cp`       | Copy a file or directory between here and the deployment, either direction.          |
| `freepod builds`   | List your builds, most recent first.                                                 |
| `freepod releases` | List this project's rollouts, most recent first; the live one is marked.             |
| `freepod delete`   | Delete this project's deployment.                                                    |
| `freepod whoami`   | Report who you are signed in as.                                                     |
| `freepod logout`   | Forget the stored credential.                                                        |
| `freepod key`      | Register the SSH public keys that identify you to the platform.                      |
| `freepod db`       | Report this deployment's database: name, role, password (masked), and quota state.   |
| `freepod db shell` | Open an interactive session in the deployment's database, server-side.               |
| `freepod db proxy` | Forward a local port to the database and print a connection URL for the local end.   |
| `freepod skill`    | Install deployment instructions for your coding agents.                              |

`freepod --help` and `freepod <command> --help` cover the flags.

## SSH keys

`freepod key add` registers an SSH public key on your account and records which
local key this machine holds, so later connections offer exactly that one. With
no argument, it generates a key for you. The key belongs to your account, not to
one deployment, and applies to every deployment you own.

The key is the credential for `shell`, `db shell`, and `db proxy`, which use ssh
to connect to your pod.
`freepod key list` shows your keys (the one this machine holds is marked `*`),
and `freepod key rm <fingerprint>` revokes one.

### Running one command

`shell` opens an interactive shell in the pod container. It can also take a
command directly:

```bash
freepod shell whoami
freepod shell 'ls -la /app | head'      # quote a pipeline to keep it whole
```

### Copying files

`cp` recursively transfers files and directories to and from your pod. Mark
the deployment's side with a leading colon; the other side is local, and which
one is marked decides the direction:

```bash
freepod cp report.csv :/app/report.csv     # copy in
freepod cp :/app/app.log ./app.log         # copy out
freepod cp ./assets :/app/assets           # a whole tree, no flag needed
```

Owners and timestamps are not preserved.

## Hostnames

`init` asks for one. A bare name becomes a subdomain of the platform: `myapp` is
served at `myapp.freepod.eu`. To use a domain of your own, point a CNAME at
`freepod.eu` first, then give `init` the full name. Certificates are issued and
renewed for you either way.

## Persistence (object and relational)

Deployments have no persistent disks or volumes. Whatever the app writes to its
own filesystem is gone when it restarts, and at every release.

Instead, each pod has its own private S3-compatible bucket for object storage.
Use with any aws-s3 client. `S3_BUCKET`, `BUCKET_NAME` and `AWS_*` environment
variables and access keys are already set.

Each deployment also gets its own PostgreSQL database. Nothing to set up:
`DATABASE_URL` and the usual `PG*` variables are already in the environment, so
any ORM or `psql` connects as-is.

`freepod db status` shows the database name, role, password, and quota usage.

To connect directly to your pod's database from your local machine:

```bash
freepod db shell                      # interactive SQL shell

# backup and restore:
freepod shell pg_dump > backup.sql
freepod shell psql < backup.sql
```

Use `freepod db proxy` to connect from an IDE, or other local DB client: it forwards a
local port and prints a connection URL for the local end.

```bash
# terminal 1: hold the tunnel; it prints the URL and waits for Ctrl+C
freepod db proxy

# terminal 2: a local client, against the URL terminal 1 printed
psql "postgresql://…@localhost:5432/<db>"
```

## Environment variables

Inject environment variables in to your pod.

```bash
freepod var set LOG_LEVEL=debug        # sets it and rolls the deployment
freepod var set ADMIN_TOKEN --secret   # prompts without echo; write-only
freepod var list
freepod var rm LOG_LEVEL
```

Setting a var rolls the deployment, because that is what makes it take effect.
Several in one command produce one rollout. `--stage` records them for your
next deploy instead, and `freepod deploy --no-build` applies staged vars
without rebuilding your entire project.

A var marked `--secret` is **write-only**: the platform never returns it, so
`var list` shows its key with the value hidden and nothing can print it back.

## .freepod.json

`init` writes it, and it is meant to be committed. It records the hostname you
chose and which deployment this directory belongs to, so the next `deploy` —
yours, a coworker's, or CI's — updates that same app instead of creating a
second one. To change a value, edit the file; the next deploy applies it.

## What gets uploaded

The working tree, minus `.git/`, anything your `.gitignore` excludes, and the
usual build output (`node_modules/`, `.venv/`, `__pycache__/`, `dist/`, …). A
`.freepodignore` file — same syntax as `.gitignore`, and applied last — keeps
out anything else the build does not need.

Re-including a file follows git's rules, with one wrinkle worth knowing: the
negation has to name the path (`!node_modules/patched.js`; a bare
`!patched.js` does nothing), and nothing beneath a directory you excluded
yourself can come back. Exclude `build/*` rather than `build/` if you need an
exception.

## Output

The address is the only thing `deploy` writes to stdout. The build log, the
progress bar and every status line go to stderr:

```bash
URL=$(freepod deploy)
```

## Deploying with a coding agent

Install the freepod skill:

```bash
freepod skill install
```

Then just prompt:

> Build a URL shortener and deploy it to freepod.

Supported: **Claude Code**, **Codex**, **OpenCode**, **Amp**, **Gemini CLI**, **Qwen Code**

---

Deployments are listed and managed at [freepod.eu](https://freepod.eu). Source
and issues: [github.com/erikvanzijst/freepod](https://github.com/erikvanzijst/freepod).
