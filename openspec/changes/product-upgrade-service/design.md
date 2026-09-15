## Context

See proposal.md § Why. The experiment behind this change is recorded in the gitignored
`var/` directory: `upgrade_product.runs.md` (16 graded dry runs) and
`upgrade_product.decisions.md` (decisions D1–D11 and the harness findings). Those files are
not in git, so this document restates every measurement it relies on.

What the experiment established (pi 0.85.1, `qwen3.8-27b-q4`, dry runs only):

- **Cost per product.** Single-product runs took 19–49 minutes and peaked at 55–95k
  tokens of context (runs 01–15). Run 12 handled three products in one session and peaked
  at 102k.
- **One inference session at a time.** The server (llama-swap in front of llama.cpp,
  OpenAI-compatible) holds a single KV cache for this model, so runs were strictly
  sequential.
- **Judgment is stochastic.** With identical skill text, run 13 mirrored upstream's Valkey
  probe fix and run 14 called it "equivalent" and missed it. A rule holds only where the
  decision is made: run 11 regressed when a rule was moved to a cross-reference.
- **The report line is not a stable format.** The prototype loop finds each product's line
  with ``grep -m1 -E "^[-* \`]*(\*\*)?$slug(\*\*)?:"`` and falls back to `tail -n 3`,
  because from run to run the model wrapped the line in backticks, bold or a bullet.
- **Effort never reached the model.** With the `models.json` of runs 01–15, pi's
  `--thinking` set only `thinking_budget_tokens` (2,048, 8,192 or 15,360). The server pins
  `--reasoning-effort medium`, so every graded run was medium effort with a cap. Run 14
  showed the cap never bound: no turn thought past about 7.6k characters. A per-request
  `chat_template_kwargs.reasoning_effort` does override the server default (verified
  through `/apply-template`).
- **Path-less searches burn the clock.** In a blobless clone, a `git grep` or pickaxe
  `git log` with no path fetches every blob, one request at a time. That took 8.5 minutes
  in run 10 (Nextcloud server) and ran for over 12 minutes in run 16 (Immich) before it was
  killed. The GPU sat idle throughout.
- **Artifact sizes.** The 16 session transcripts are 300–430 KB each, 5.0 MB in total, and
  the largest gzips to 116 KB. pi's HTML export of the largest is 841 KB. PR bodies reach
  46 KB; the skill caps them at 60,000 characters.

What the platform provides, checked against the running cluster and the repository:

- **Egress to the inference endpoint works.** From three running `custom` pods,
  `ai.deprutser.be` resolves to 185.142.224.235, a public address outside the private
  ranges that `deployment-network-isolation` denies. An unauthenticated `GET /v1/models`
  from those pods answered 401.
- **The shared relay is reachable** under the same policy. Product charts address it as
  `smtp.mailer.svc.cluster.local:25` with no credentials, and Nextcloud sends as
  `nextcloud@freepod.eu`.
- **The tenant pooler** runs `pool_mode = transaction` with `max_prepared_statements = 100`
  (`tf/app/caelus/tenant-pooler.tf`). Driver-side prepared statements therefore work, but
  session state does not: no `SET`, no `LISTEN`/`NOTIFY`, no session advisory locks, no
  temporary tables. The role has a 30s `statement_timeout` and a 60s
  `idle_in_transaction_session_timeout`.
- **No resource limits and no disk.** The `custom` chart sets `resources: {}`. The
  container filesystem is the only scratch space, and it is lost on every restart. The
  bucket has no plan quota: `storage_bytes` bounds block storage only.
- **CI on branches.** `ci.yml` runs on `pull_request` for every branch, and every PR job
  has `contents: read` and uses no secrets. Image and chart publishing run only on a push
  to `master` (`ci.yml:106`). `publish-cli.yml` publishes the CLI to PyPI on any push of a
  `freepod-v*` tag, through the `pypi` environment, which has no protection rules today.
  The repository has no rulesets and no branch protection.
- **pi 0.85.1** is the current npm release of `@earendil-works/pi-coding-agent`. Its
  documentation defines `"apiKey": "$NAME"` in `models.json` as a value resolved from the
  environment.

## Goals / Non-Goals

**Goals:**

- Every curated product is checked every night, with nobody starting it.
- Every PR the agent opens is reviewed by a human before anything ships, and the service's
  reach on GitHub cannot exceed that even when its agent is misled.
- A run can be understood afterwards from the dashboard alone: what was decided, from which
  skill commit, with the full transcript.
- Small enough to read in one sitting. A failed or interrupted run is an acceptable outcome
  for an internal tool, because the next night repeats the work.

**Non-Goals:**

- Surviving a restart in the middle of a run. No locks, leases, heartbeats, resumption or
  retries (D5).
- Parallel sessions. The inference server serves one.
- Retention or pruning.
- CI auto-deploy of the service.
- Moving existing deployments onto new templates. The skill already declares that out of
  scope.
- Being a platform feature. Nothing in `api/`, the reconciler or the UI knows the service
  exists.

## Decisions

### D1: One process, with runs on a background thread

Freepod gives a deployment one container and one HTTP service, and runs no scheduled jobs.
So the scheduler lives in the dashboard's process. uvicorn serves the dashboard with a
single worker, and runs execute one at a time on a background thread. The entrypoint
applies migrations before the server starts (`alembic upgrade head && exec uvicorn …`),
under `tini -s`.

The long-running work is already a separate process tree: pi and everything it spawns.
What runs in the service's process is the loop that starts pi, waits for it, and redacts
and uploads its files. That loop runs on a plain thread with blocking subprocess, S3 and
SMTP calls, so the event loop only serves pages. Keeping it in one process lets a lock
replace what two processes would have to coordinate through the database (D5).

Two constraints follow:

- **One worker, and no `--reload` in the image.** A second worker would be a second
  scheduler with a lock of its own.
- **`tini`, as a subreaper.** The timeout kills pi's process group (D12), and a process
  whose parent has died is handed to the nearest subreaper, or else to PID 1. uvicorn
  reaps no such processes, so they would stay behind as zombies. On Freepod the pod's
  containers share one process namespace, so PID 1 is the pod's `pause` process, not
  tini; `-s` registers tini as a subreaper, and in a plain container it is PID 1 anyway.

*Alternative considered:* the dashboard and the scheduler as two processes under
supervisord, each restarted on its own. That protects a run only from the dashboard
process dying by itself, which is unlikely: uvicorn catches an exception in a request
handler without exiting. Every rollout and every `freepod var set` restarts the whole
container either way. In exchange, two processes need a request table with a partial
unique index, a polling loop, and supervisord with its configuration.

*Alternative considered:* an external trigger, such as a GitHub Actions schedule calling an
endpoint. It adds an inbound, authenticated trigger surface, and a long-lived process is
still needed to run the session.

The Freepod skill's "no worker processes" holds: the platform sees one process. Any
rollout (`freepod deploy`, or any `freepod var set`) restarts the container and
interrupts an active run (D5).

### D2: Each product reads the skill from its own clone of `master`

Each product session reads the skill from its own fresh clone of `master`, and the service
records that clone's commit. The skill changed after almost every one of the 16 runs.
Baking it into the image would tie every edit to an image build and a deploy, and would
let the deployed copy drift from the reviewed one. The skill's step 0 already resets its
clone to `origin/master`, so the catalog, the charts and the skill a session sees all
come from one commit.

The clone is a `--depth 1` clone of `master`. The repository's own clone is not blobless;
the skill makes blobless clones of upstream repositories itself.

*Alternative considered:* bake the skill into the image, or pin it to a tag. Rejected
because of the drift above. The cost is that a bad skill change reaches the next night's
run as soon as it merges. That holds for any change to `master`, and the history shows
which commit each product ran.

### D3: One product per session, strictly sequential (experiment D11)

Run 12, three products in one session, peaked at 102k tokens, against 56–95k for one
product. Runs 09 and 11 cut corners on Immich inside a shared session: run 09 wrote only
`meta.json`, and run 11 wrote nothing at all. A shared session would also reach
compaction as the catalog grows. A fresh session and clone per product also makes each
transcript self-contained, which is the unit the history stores.

Products run one after another because the inference server holds one KV cache. A second
concurrent session would queue behind the first or evict it.

### D4: A result file, not prose

The service needs a handful of facts per product, and the prose report is not a stable
carrier for them (see Context). `result.json` is an explicit contract that a runner can
validate. A missing or malformed file, or a file for another product, is a failure the
service can name.

Choices within the contract:

- `would_open` and `would_skip` are statuses of their own, not `opened` plus
  `dry_run: true`. A dry-run outcome must never read as a PR that exists, in the index or
  in an email.
- `draft` is a flag, not a status. Drafts and ready PRs are opened the same way, and the
  dashboard and the email treat them alike apart from the decisions in `needs_human`.
- `needs_human` repeats the PR's *Needs human review* section as a list, so an email can
  name the decisions without the reader opening the PR.
- `body.md` and `change.patch` are written in real runs too, not only in dry runs. That
  keeps the history uniform, and a real PR's original description survives later edits
  on GitHub.
- The dry-run `meta.json` stays as it is. Its fields overlap `result.json`, but it is what
  the 16 runs validated, and run 11 showed that reshuffling output rules regresses the
  model. Folding it in is a later cleanup.
- Following run 11's lesson, the instruction to write `result.json` goes at every point
  where the procedure ends (up to date, each skip, a missing image, a PR opened, a
  failure), not only in *Run report*.

*Alternative considered:* parse pi's `--mode json` event stream for the final message.
That extracts the message reliably, but the message is still prose.

### D5: One lock; no leases or retries

A run starts only once the service holds its run lock, an in-memory lock that covers the
whole run. "Run now" and "Run one product" try to take it without waiting and are refused
when it is held, so a double click cannot start two runs and nothing is queued. The
nightly trigger waits for it instead, so a scheduled time that passes during a run starts
when that run finishes (D11). The run thread releases the lock in a `finally`, so an
exception fails the run rather than blocking every later one.

The dashboard shows a run as active while the lock is held. Its progress panel reads the
run and product-result rows, which are written as the run goes.

When the service starts, one `UPDATE` marks every unfinished run and product result
`interrupted`. Nothing more is needed, because the only process that could have been
running them is the one now starting.

Nothing retries. The next night covers every product again, and the skill's duplicate
checks make a repeat safe: they find any PR or branch that a cut-short real run left on
GitHub, and skip the product.

Session-level advisory locks would not work anyway, because the pooler runs in transaction
mode. A lease with heartbeats would add code whose only job is a case this tool can
shrug off.

The pooler also sets the database discipline. Every state change commits at once, no
transaction stays open across a session (the role's idle-in-transaction limit is 60s),
and no statement needs `SET`.

### D6: Postgres indexes the runs, the bucket keeps the files

The database holds what the dashboard queries: small rows per run and per product. The
files go to the bucket under `runs/<run-id>/<slug>/`: `session.jsonl`, `session.html`,
`stdout.txt`, `result.json`, `body.md` and `change.patch`. They are kept forever.

The measurements give an upper bound on growth. If all three products went through a full
review every night, each would store about 0.43 + 0.84 + 0.05 MB, so 4 MB a night and
1.4 GB a year. An up-to-date product ends at step 2 with a much shorter session, so the
real figure is a fraction of that. The bucket has no plan quota and draws on the node's
disk through Garage.

Signed URLs serve the files straight from the object store. This also puts each
transcript, which quotes untrusted upstream content, on the store's origin
(`blob.freepod.eu`) rather than the dashboard's, so nothing in it can act on the
dashboard's session.

*Alternative considered:* transcripts in the database. The database has a size allowance,
and at 100% it turns read-only. That is the wrong way to fail for megabytes of logs.

*Alternative considered:* render the HTML on demand. That would put pi on the dashboard's
request path. Storing the export is simpler, and a signed link serves it without the
bytes passing through the container.

### D7: The model configuration is generated at startup

On start, the service writes `models.json` into a pi agent directory it owns
(`PI_CODING_AGENT_DIR`), filled in from the vars:

```json
{
  "providers": {
    "upgrader": {
      "baseUrl": "<INFERENCE_BASE_URL>",
      "api": "openai-completions",
      "apiKey": "$INFERENCE_API_KEY",
      "compat": {
        "supportsDeveloperRole": false,
        "thinkingFormat": "chat-template",
        "thinkingTokenBudgetField": "thinking_budget_tokens",
        "chatTemplateKwargs": { "reasoning_effort": { "$var": "thinking.effort" } }
      },
      "models": [
        {
          "id": "<INFERENCE_MODEL>",
          "reasoning": true,
          "contextWindow": 200000,
          "thinkingLevelMap": { "minimal": "low", "max": "xhigh" }
        }
      ]
    }
  }
}
```

This is the configuration prepared for runs 16 and 17 and checked against a mock server:
`--thinking low`, `medium`, `high` and `xhigh` each send the `reasoning_effort` of the same
name. `thinkingLevelMap` exists because the Qwen3.8 template accepts only `xhigh`,
`medium` and `low`, and errors on anything else. The key never lands in a file: pi reads
`$INFERENCE_API_KEY` from the environment.

`preserve_thinking` stays at the server's default, which is on. Without it, run 10 took
50% more turns and 70% more thinking, with no better result.

Each session runs with `-p` and the prototype's prompt, plus:

- `--no-context-files`, because the skill reads `AGENTS.md` itself in step 0;
- `--session-dir` inside the product workspace;
- `PI_TELEMETRY=0`.

### D8: The App's permissions and the rulesets bound GitHub access; the guards keep the normal path inside that bound

The agent runs shell commands, it reads untrusted content, and the pod can reach the
whole public internet. Nothing inside the container can stop a sufficiently misled agent
from calling GitHub directly, with `curl` or the real `gh` binary. So the bound is set on
GitHub's side, by what the service's identity is allowed to do.

**A GitHub App, installed on one repository.** The App is registered under the owner's
account and installed on `erikvanzijst/freepod` only. Its repository permissions are
Contents write, Pull requests write and Metadata read. Contents write is the least that
can push a branch, and Pull requests write the least that can open a PR; it also covers
creating a label, so Issues is not needed. Without Workflows, GitHub refuses any push
that creates or changes a workflow file. Without Actions, the App cannot dispatch or
re-run a workflow. Its tokens reach no other repository, so a misled agent cannot open
issues or PRs, or comment, on upstream projects.

*Alternative considered:* a machine user with a classic token scoped to `public_repo`.
That scope lets its holder act as any signed-in user on every public repository, and it
brings a second account, its email, and a yearly renewal. A fine-grained token cannot
replace it: GitHub does not allow one on a repository where its owner is only a
collaborator. A fine-grained token on the owner's account would reach only this
repository, but it would act as the owner, who is the rulesets' bypass actor, so it could
merge, push to `master` and push tags.

**Rulesets confine the App's writes.** Contents write reaches every branch and tag, and it
is also the permission that merges a PR. Two rulesets narrow it. Each is bypassed only by
the Repository admin role, in "Always allow" mode, because the owner pushes to `master`
directly and "For pull requests only" would refuse that:

- *Branches:* every branch except `refs/heads/upgrade/**`, with "Restrict creations",
  "Restrict updates" and "Restrict deletions". A merge updates the base branch, so the
  App cannot merge into `master`, push to it, or touch any branch outside `upgrade/`.
- *Tags:* every tag, with "Restrict creations", "Restrict updates" and "Restrict
  deletions". `publish-cli.yml` publishes to PyPI on any `freepod-v*` tag, so without
  this rule the App could publish a build of any commit it had pushed.

*Alternative considered:* the owner as a required reviewer on the `pypi` environment, so a
publish waits for approval whoever pushed the tag. Rejected: the tag ruleset already refuses
every tag to anyone but the owner, CI's own token included, and an admin can bypass an
environment's reviewers by default. The reviewer would stop no one the rulesets let through,
and it would add a click to every release for the one case of the tag ruleset being turned
off by mistake.

What the App can still do, in this repository only: create, update and delete `upgrade/*`
branches, and open, edit, close, label and comment on any PR. It cannot ship anything.
Shipping is a push to `master` or a tag, and a PR it opens runs only the `ci.yml` PR jobs,
which have `contents: read` and no secrets.

**Tokens.** The service holds the private key and the App id. It finds the installation
from the repository and mints installation tokens limited to `erikvanzijst/freepod`. A
token lasts one hour and a product session can last 90 minutes, so the run thread writes
the current token to a file outside the workspace and replaces it before it expires. The
git credential helper and the `gh` guard read that file on every call. The key never
enters the session's environment.

A dry-run session's tokens are minted with read access only. The mint request names the
permissions, so this costs one parameter and no operator step. The dashboard mints its own
read-only token for PR states (D13).

**The key is within the agent's reach.** The agent runs as the same Unix user as the
service, so it can read the key from the service's environment (`/proc/<pid>/environ`). An agent set on it can mint a token with every permission the App
has, in a dry run too. The App's registered permissions and the rulesets are therefore
the real ceiling, not the tokens a session is handed.

*Alternative considered:* register the App read-only for the dry-run phase, so dry runs
stay write-proof even against that. Rejected as an extra operator step for a phase that
ends with the App holding write access anyway.

*Alternative considered:* run the agent as a separate Unix user that cannot read the key.
That would make the session's tokens and the guards a real boundary. It is more machinery
than this tool warrants while the App's reach is already bounded.

The guards are not that boundary. They stop an agent that is following (or misreading)
its instructions from doing damage by ordinary means:

- **The `gh` guard** is ported from the experiment's `bin/gh`. It allows read-only
  commands, `pr create`, `label create`, `auth status` and `auth setup-git`, and in a dry
  run it allows no writes at all. It sets `GH_TOKEN` from the token file for the real
  binary. It refuses `auth token`, so the normal path never prints a token into a
  transcript, and redaction (D10) catches the rest. git gets its credentials from a
  helper, configured at startup, that reads the token file. So `gh auth setup-git`, which
  the skill runs in step 0, can succeed as a no-op, and `gh auth git-credential` need not
  be allowed.
- **A pre-push hook** is installed through the system git configuration
  (`core.hooksPath`), so every clone gets it. It refuses any ref outside
  `refs/heads/upgrade/`, and in a dry run it refuses every push. A hook can be skipped
  with `--no-verify`; the branch ruleset then refuses the push on GitHub's side.

Both guards, and the `git` guard (D9), sit ahead of the real binaries in the agent's
`PATH`.

**Commit identity.** At startup, the service asks GitHub for the App's slug (`GET /app`)
and its bot user's id (`GET /users/<slug>[bot]`). They become the system git `user.name`
(`<slug>[bot]`) and `user.email` (`<id>+<slug>[bot]@users.noreply.github.com`). No extra
var is needed.

**The key.** `GITHUB_APP_PRIVATE_KEY` holds the PEM file base64-encoded on one line,
because the CLI's hidden prompt reads a single line. The key does not expire. To rotate
it:

1. Generate a new private key in the App's settings.
2. Run `freepod var set GITHUB_APP_PRIVATE_KEY --secret` outside the nightly window, and
   paste the output of `base64 -w0` on the new key file.
3. Delete the old key in the App's settings.

Deleting the key or suspending the installation cuts the service off at once. Every
product then fails on its first GitHub call, which sends the failure email.

### D9: The git guard makes history searches name their paths

A second guard sits in `PATH` next to the `gh` guard. It refuses `git grep`, and
`git log` with `-p`, `--patch`, `-S`, `-G` or any `--pickaxe` option, unless a pathspec
follows `--`. Every other command passes to git unchanged. It is the experiment's
`bin/git`, which was tested to refuse `git grep -c foo v3.2.1` and to pass
`git log -S 'x' a..b -- docker/`.

This guard is about time, not security. The skill makes blobless clones of upstream
repositories, where every file read is a network fetch, and a path-less search fetches the
whole repository one blob at a time. That took 8.5 minutes in run 10 and over 12 in
run 16 (killed), with the GPU idle and the product's timeout running.

The skill's step 5 now tells the agent to path-limit these commands, but runs 11 and 14
showed that a rule in the skill is followed only some of the time. A refusal whose message
says "add `-- <path>`" is followed every time.

The guard applies to every repository, including the service's own shallow clone of
`freepod`, where a path-less search would be harmless. Telling blobless clones apart would
cost more code than adding a path costs the agent.

`git show` and `git diff` without paths are left alone. Between two refs they fetch only
the files that changed.

### D10: Redaction by value

Before any upload, and before any value from a session reaches the database, every
occurrence of a secret is replaced with a marker naming it. The secrets are every
installation token minted during the run, the value of `GITHUB_APP_PRIVATE_KEY` and the
key it decodes to, and the current values of `INFERENCE_API_KEY` and
`DASHBOARD_PASSWORD`. Each line of the key's body is replaced on its own too, so a
partial print is caught. The HTML is exported from the already-redacted JSONL, so it
cannot reintroduce a value.

Redaction catches literal copies only; an encoded form (base64, URL-encoded) would get
through. The likely ways a literal copy gets printed are `gh auth token`, reading the
token file, and echoing the environment. The first is refused outright, and the key is
not in the session's environment.

### D11: The schedule is a time and a zone

`SCHEDULE_TIME` (`HH:MM` or `off`) plus `SCHEDULE_TIMEZONE` replace a cron expression. The
service needs one run a day, and a time plus an IANA zone states that without a parser.

The next-run computation follows the zone's rules. A time skipped in spring runs at the
first valid instant after it, and a time repeated in autumn runs once. 03:00 in Brussels
is never skipped or repeated.

A missed time is not caught up, because the scheduler computes the next occurrence from
the service's start. The scheduler thread sleeps until the next occurrence, then waits
for the run lock (D5), so a scheduled time that passes during a run becomes due when that
run finishes.

### D12: Timeouts and workspaces

`PRODUCT_TIMEOUT_MINUTES` defaults to 90. The graded dry runs took 19–49 minutes, and a
real run adds the wait for CI (`gh pr checks --watch`).

The session starts in its own process group, so the timeout can terminate pi together
with everything it spawned: clones, helm, uv. When the product ends, its workspace is
deleted: the `freepod` clone, the upstream clones, and the session file once it has been
uploaded.

uv's download cache lives outside the workspace and is kept for the container's lifetime.
Every product's `caelus catalog lint` syncs the same `api/` dependencies, so the cache
saves the same download each time.

### D13: The dashboard

The dashboard uses FastAPI with Jinja templates and htmx, managed with uv like `api/`.
Pages are rendered on the server, with no JavaScript build step. The progress panel is an
htmx fragment that polls every five seconds.

Authentication is HTTP Basic with one secret. The password is compared in constant time,
and the username is ignored because there is one user. An unset password refuses
everything rather than admitting everyone.

PR states come from GitHub's REST API, with an installation token the dashboard mints
with read access to pull requests only (D8), and are cached in memory for five minutes.
A page load then costs at most one request per PR not already cached, well inside
GitHub's limit of 5,000 requests an hour.

### D14: Email only when something needs the owner

The service sends one email per run, when the run ends, and only if a product opened (or
would open) a PR, failed, or timed out. A night of "up to date" sends nothing, so an email
always means there is something to do.

The relay needs no credentials from inside the cluster. The sender is
`upgrader@freepod.eu`, on the domain the product charts already send from. An interrupted
run sends nothing: the process that notices the interruption is only just starting, and
the dashboard shows it.

### D15: Where it lives, how it ships, how it is tested

The service lives in `ops/upgrader/` in the monorepo, next to the skill it runs and the
catalog it reads, but outside `api/`. It imports nothing from the platform and ships on
its own cadence.

It is deployed by hand with `freepod deploy` from that directory, which uploads only that
directory. `.freepod.json` is committed so every deploy updates the same deployment. The
image is built from a root `Dockerfile` because its tools span more than one Railpack
stack: Node.js for pi, `gh`, `helm`, Python with uv, and `tini`.

The prototype `var/upgrade_products.sh` moves to `ops/upgrader/` as the local runner, and
reads `result.json` instead of grepping the report.

pytest covers the parts with logic:

- the next-run time;
- redaction;
- minting installation tokens, and replacing one before it expires;
- `result.json` validation;
- the allow and deny cases of both guards and the push hook;
- product discovery;
- session statistics;
- the run lock and the scheduler's state changes.

S3, SMTP, GitHub and pi are faked. The fake pi is an executable that, depending on the
test, writes a session file and a `result.json`, writes no result, or sleeps past the
timeout. Tests that touch the database run against a real Postgres, as `api/`'s do,
because the behavior under test there (the interrupted-run update) is Postgres behavior.

## Risks / Trade-offs

- [A rollout interrupts an active run] → Deploy and change vars away from the nightly
  window. The run is marked `interrupted`, and the next night repeats it.
- [An interrupted real run can leave an `upgrade/*` branch with no PR] → The skill's
  duplicate check then skips that product on every later run, with "branch exists" as the
  reason. The dashboard shows that reason, and deleting the branch releases the product;
  the ops README says how.
- [The model's judgment is stochastic (runs 13 and 14)] → A human reviews every PR before
  merge. Chart changes and major versions open as drafts, and the full transcript is kept
  so a wrong call can be traced.
- [Prompt injection with GitHub write access in reach] → The App's permissions and the
  rulesets bound the damage to `upgrade/*` branches and PRs in this repository (D8).
  Nothing merges or tags without the owner.
- [The CI of an App PR runs code from the App's branch] → PR jobs have `contents: read`
  and no secrets. Publishing needs a push to `master` or a tag, which the rulesets
  refuse the App, and without the Workflows permission a branch cannot change the
  workflows.
- [The private key is readable by the agent, and does not expire] → An agent that reads it
  can mint tokens with the App's full permissions, which the rulesets still bound (D8).
  Rotating the key, or suspending the installation, revokes it at once.
- [Memory pressure from large clones] → On the development machine, blobless-clone
  operations filled the page cache and set off the harness's low-memory check (runs 02
  and 10). The git guard removes the worst case. The `custom` chart sets no memory limit,
  so pressure lands on the node, and a killed container becomes an interrupted run.
- [The inference endpoint is down or slow] → Products fail or time out, and the run sends
  a failure email. Nothing retries before the next night.
- [Redaction misses encoded forms] → See D10.
- [A signed link works for anyone holding it, for up to an hour] → It grants read access
  to one object, and the dashboard renders it only after authentication.
- [History grows without bound] → The upper bound is about 1.4 GB a year (D6). Revisit it
  if that approaches the node's disk budget.
- [A dry run can still write if the agent sets out to] → A dry-run session's tokens are
  read-only and the guards refuse writes, but the key is in reach (D8). Accepted: the App
  gets write access when the service goes live anyway, and the rulesets bound it in both
  modes.

## Migration Plan

1. Merge the change: the skill, the READMEs and the service code. Nothing runs yet, since
   the skill in `products/UPGRADING/` is inert without a runner.
2. The operator registers and installs the App, and creates the two rulesets (tasks § 9).
3. Run `freepod init` from `ops/upgrader/`, stage the vars and secrets, and run
   `freepod deploy`. The service starts in dry-run mode.
4. Trigger one product from the dashboard. Then let the nightly run go for several nights,
   comparing its would-be PRs with what a human would have opened.
5. Switch to real PRs with `freepod var set UPGRADE_DRY_RUN=0`, outside the nightly window.

Rollback options, at any point:

- `freepod var set UPGRADE_DRY_RUN=1` returns the service to dry runs.
- `freepod delete` in `ops/upgrader/` removes the service and its history.
- Suspending the App's installation, or deleting its private key, cuts its GitHub access
  at once.

## Open Questions

- **The default `THINKING_LEVEL`.** Runs 16 (`xhigh`) and 17 (`low`) are the first in
  which effort actually reaches the model, and they are still pending. Until they are
  graded, the service ships `medium`, which reproduces what every graded run (01–15) used:
  the server's pinned default, now sent explicitly. Changing the default later means
  setting a var, not changing a spec or code.
- **The per-product timeout.** 90 minutes covers the measured dry runs with margin. The
  first real runs, which wait for CI, will show whether it needs to move.
- **Folding `meta.json` into `result.json`.** Deferred (D4) until the skill has run
  unattended for a while.
