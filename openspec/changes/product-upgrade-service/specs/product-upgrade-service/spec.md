## Purpose

The upgrade service as a Freepod deployment: what its image carries, how it serves the
dashboard and executes runs, the configuration it takes, and how it points the agent at a
model. It is an
ordinary `custom` tenant and relies on nothing a tenant is not given.

## ADDED Requirements

### Requirement: The service is an ordinary custom deployment
The service's source MUST live in `ops/upgrader/`, with a root `Dockerfile` and a
committed `.freepod.json`, and MUST be deployable by running `freepod deploy` from that
directory.

It MUST rely only on what every `custom` deployment is given. It binds `0.0.0.0:$PORT`,
keeps nothing on its own filesystem that must survive a restart, and holds its state only
in the deployment's Postgres database and S3 bucket.

#### Scenario: Deploying from the service directory
- **WHEN** the owner runs `freepod deploy` in `ops/upgrader/`
- **THEN** the image is built from `ops/upgrader/Dockerfile`
- **AND** the release updates the deployment that `ops/upgrader/.freepod.json` names

#### Scenario: A restart loses no history
- **WHEN** the container restarts
- **THEN** every run and product result recorded before the restart is still shown with its stored files

### Requirement: The image pins its tooling and carries no skill
The image MUST carry these tools, each at a version pinned in the `Dockerfile`: Node.js,
the pi coding agent (`@earendil-works/pi-coding-agent`), `gh`, `git`, Python with `uv`,
`helm`, `jq` and `curl`.

The image MUST NOT carry the upgrade skill or the product catalog. Both are read from a
fresh clone of `master` for each product (see `product-upgrade-runs`).

#### Scenario: Rebuilding gives the same tools
- **WHEN** the same source is built twice, some time apart
- **THEN** both images report the same version of every tool listed above

#### Scenario: A skill change needs no image
- **WHEN** a product session starts after a skill change was merged to `master`
- **THEN** the session follows the merged skill on the image already deployed

### Requirement: One process serves the dashboard and executes runs
The container MUST run a single server process, with one worker, that serves the dashboard
and executes runs on a background thread. A run MUST NOT keep the dashboard from answering.

PID 1 in the container MUST be an init process that reaps orphaned processes, so that no
process a terminated session leaves behind remains as a zombie.

Database schema migrations MUST be applied when the container starts, before the server
starts.

The dashboard MUST answer `GET /healthz` with status 200, and without authentication.

#### Scenario: Pages answer during a run
- **WHEN** a product is running
- **THEN** dashboard pages and `/healthz` answer as they do when no run is active

#### Scenario: A timed-out session leaves no zombies
- **WHEN** a product times out and its session's processes are terminated
- **THEN** none of those processes remains in the container's process table

#### Scenario: A release with a schema change
- **WHEN** a release that adds a migration starts
- **THEN** the migration is applied before the server binds its port, and so before any run can start

#### Scenario: Health check
- **WHEN** `GET /healthz` is requested without credentials
- **THEN** the response has status 200

### Requirement: Configuration arrives as deployment vars
The service MUST take its configuration from environment variables that the owner sets as
Freepod vars. The following three MUST be set with `freepod var set --secret`, because
the platform never returns a secret var:

- `GITHUB_APP_PRIVATE_KEY`: the GitHub App's private key, base64-encoded on one line,
  because the CLI's hidden prompt reads a single line.
- `INFERENCE_API_KEY`: the key for the inference endpoint.
- `DASHBOARD_PASSWORD`: the dashboard's password.

The plain vars, with defaults where one exists:

- `GITHUB_APP_ID`: the GitHub App's id. Required. The installation is looked up from the
  repository, so no installation id is configured.
- `INFERENCE_BASE_URL`: the inference endpoint's base URL. Required.
- `INFERENCE_MODEL`: the model id. Required.
- `THINKING_LEVEL`: the agent's thinking level.
- `SCHEDULE_TIME`: the local time of the nightly run, `HH:MM`, or `off`. Default `03:00`.
- `SCHEDULE_TIMEZONE`: an IANA zone name. Default `Europe/Brussels`.
- `UPGRADE_DRY_RUN`: `0` for real pull requests. Any other value, or none, means a dry run.
- `PRODUCT_TIMEOUT_MINUTES`: the per-product time limit. Default `90`.
- `NOTIFY_EMAIL`: the notification recipient. When unset, no email is sent.
- `NOTIFY_FROM`: the sender address. Default `upgrader@freepod.eu`.
- `SMTP_HOST`: the mail relay. Default `smtp.mailer.svc.cluster.local`.
- `DASHBOARD_URL`: the dashboard's public URL, used for links in emails. Optional.

The service MUST NOT require any var whose name the platform reserves or overrides:
`PORT`, `BUCKET_NAME`, `DATABASE_URL`, and anything starting with `AWS_`, `S3_`, `PG`,
`CAELUS_` or `RAILPACK_`. It reads the platform-provided values under those names as they
are.

#### Scenario: Optional vars are unset
- **WHEN** the service starts with only the required vars and secrets set
- **THEN** it runs dry, schedules the nightly run at 03:00 Europe/Brussels, and sends no email

#### Scenario: A required var is missing
- **WHEN** a run starts while `INFERENCE_BASE_URL` is unset
- **THEN** the run's products are recorded as `failed` with an error naming `INFERENCE_BASE_URL`
- **AND** the dashboard stays available

### Requirement: The agent's model is configured from vars without writing the key to disk
At startup, the service MUST generate the agent's model configuration from
`INFERENCE_BASE_URL` and `INFERENCE_MODEL`, declaring an OpenAI-compatible provider.

The configuration MUST reference the API key through the `INFERENCE_API_KEY` environment
variable, and no file the service writes MUST contain the key itself.

The thinking level MUST reach the model as the chat template's `reasoning_effort`
argument on every request, not only as a thinking-token budget. The pi levels `minimal`
and `max` MUST be sent as `low` and `xhigh`, because those are the nearest values the
model's template accepts.

#### Scenario: No key on disk
- **WHEN** the generated model configuration is read
- **THEN** it names the `INFERENCE_API_KEY` variable and does not contain its value

#### Scenario: The thinking level reaches the model
- **WHEN** a session runs with `THINKING_LEVEL=low`
- **THEN** every inference request carries `reasoning_effort` `low` as a chat template argument

#### Scenario: A level the template does not know
- **WHEN** a session runs with `THINKING_LEVEL=max`
- **THEN** every inference request carries `reasoning_effort` `xhigh`
