## 1. Skill graduation

- [x] 1.1 Add `var/upgrade_product.md` to git, unchanged, as `products/UPGRADING/SKILL.md`, in its own commit — verify `git diff --no-index var/upgrade_product.md products/UPGRADING/SKILL.md` prints nothing
- [x] 1.2 Apply `var/proposed_readme_changes.patch` to the Immich and Nextcloud READMEs — verify `git apply --check` passes first, and that afterwards both "Upstream references" sections carry the additions
- [x] 1.3 Write the `result.json` contract from `product-upgrade-skill` as a JSON Schema at `products/UPGRADING/result.schema.json` — verify a test accepts one example per status, and rejects a `failed` result without `error`, a `skipped` result without `skip_reason`, and an `opened` result without `pr_url`
- [x] 1.4 Check the skill's `result.json` instructions (D4), which the `var/` copy already carries into the repository through 1.1 — verify each `status` value is named at the step that produces it, and that the dry-run output rules in step 2.5 are unchanged

- [x] 1.5 End the pull request description with a link to the run when `UPGRADE_RUN_URL` is set, and with none when it is empty — verify the skill names the run page rather than a stored file, whose signed link expires within the hour

## 2. Service skeleton (`ops/upgrader/`)

- [x] 2.1 Create the uv project (`pyproject.toml`, lockfile, package layout, pytest configuration) — verify `cd ops/upgrader && uv run pytest` runs green
- [x] 2.2 Read configuration from the vars in `product-upgrade-service`, with their defaults, and report a missing required var by name — verify unit tests for the defaults, for `UPGRADE_DRY_RUN` parsing (only `0` means real), and that no reserved name is required
- [x] 2.3 Add the models and Alembic migrations for runs and product results — verify `alembic upgrade head` on an empty local Postgres
- [x] 2.4 Write the `Dockerfile`, pinning Node.js, pi 0.85.1, `gh`, `git`, Python, uv, `helm`, `jq`, `curl` and `tini`, with no skill or catalog copied in — verify `docker build` succeeds, and `pi --version` prints `0.85.1` in the image
- [x] 2.5 Add the entrypoint (D1): `tini -s`, running `alembic upgrade head && exec uvicorn` with one worker — verify with `docker run -e PORT=8080` against a local Postgres that `/healthz` answers 200, and, with another process as PID 1 (`docker run --init`), that a child process whose parent is killed is re-parented to tini and does not remain as a zombie
- [x] 2.6 Move `var/upgrade_products.sh` to `ops/upgrader/` as the local runner. Point it at `products/UPGRADING/SKILL.md`, have it pass `UPGRADE_OUT_DIR`, and summarize from `result.json` instead of grepping the report — verify it runs one product end to end on the development machine
- [x] 2.7 Run regression dry runs of the graduated skill through the local runner, on the experiment's fixtures: the run 07 Vaultwarden scenario and the run 15 Immich scenario — verify both reach their earlier grades, and each writes a `result.json` that validates against the schema

## 3. Guardrails

- [x] 3.1 Port the experiment's `bin/gh` as the `gh` guard: the allow list from `product-upgrade-guardrails`, refusing `auth token`, and refusing `pr create` and `label create` in dry-run mode — verify table-driven tests for each allow and deny case, including `api -X POST`, `api -f` without an explicit GET, `pr merge`, `repo` writes, and `auth setup-git` succeeding
- [x] 3.2 Port the experiment's `bin/git` as the `git` guard (D9), calling the image's real git — verify table-driven tests that refuse `git grep -c foo v3.2.1`, `git log -p a..b`, `git log -S x a..b` and `git log --pickaxe-regex -S x a..b`, and that pass `git log -S 'x' a..b -- docker/`, `git -C repo grep foo -- src/`, `git log --oneline a..b` and `git diff a b`
- [x] 3.3 Add the pre-push hook, installed through the system `core.hooksPath` — verify tests against a local bare remote: `upgrade/*` pushes pass in real mode, `master` and `nextcloud-34.0.4` are refused, and every push is refused in dry-run mode
- [x] 3.4 Mint installation tokens from `GITHUB_APP_ID` and `GITHUB_APP_PRIVATE_KEY` (D8): look up the installation from the repository, limit each token to it, request read and write in real runs and read only in dry runs, write the current token to the token file, and replace it before it expires. The dashboard mints its own token with pull requests read only — verify tests with a fake GitHub: a dry-run session's mint requests only read permissions, a session longer than a token's lifetime gets a fresh token before the old one expires, the dashboard requests only pull requests read, and a `GITHUB_APP_PRIVATE_KEY` that is not base64 of a PEM key is reported by name
- [x] 3.5 At startup, set the commit identity from the App's bot user (`GET /app`, then `GET /users/<slug>[bot]`), and configure git's credential helper to read the token file. Have the `gh` guard set `GH_TOKEN` from the same file. Put all three guards first in the session's `PATH` — verify in the image that the key is absent from the session's environment and from every file under `/etc`, `/opt` and `$HOME`, and that a commit in a scratch repository carries the bot's noreply address

## 4. Runs

- [x] 4.1 Implement product discovery from a clone's catalog — verify tests: the `OWNER/REPO` placeholder is excluded, a file without `upstream` is excluded, and the rest come back in slug order
- [x] 4.2 Implement the next-run computation (D11) — verify tests for 03:00 on an ordinary day, both `Europe/Brussels` transitions with `SCHEDULE_TIME=02:30`, `off`, and a start after the day's time (no catch-up)
- [x] 4.3 Generate `models.json` at startup (D7), and build the pi invocation: `PI_CODING_AGENT_DIR`, `-p`, `--no-context-files`, `--session-dir`, `--skill`, `--thinking`, and the `UPGRADE_*` environment — verify a test that the file references `$INFERENCE_API_KEY` and does not contain its value; and, against a mock OpenAI-compatible server, that `THINKING_LEVEL=low` sends `reasoning_effort` `low` and `max` sends `xhigh`
- [x] 4.4 Implement the per-product executor. It creates a fresh workspace and a `--depth 1` clone of `master`, records the commit, runs pi in its own process group under the timeout, and deletes the workspace — verify tests with a fake pi for success, no result, a malformed result, the wrong product, a `dry_run` mismatch, and a timeout that also terminates a child process; and that the workspace is gone after each case
- [x] 4.5 Extract session statistics from the transcript: input and output token totals, and peak context (the largest input plus cache read) — verify against a trimmed fixture transcript from the experiment with known totals
- [x] 4.6 Implement the scheduler (D5): the interrupted-run `UPDATE` on start; the run lock, taken without waiting by a request and with waiting by the nightly trigger, and released in a `finally`; the run thread; and a missing required var failing the run's products — verify tests: a restart marks unfinished rows `interrupted` (Postgres-backed), a request while a run holds the lock is refused, a scheduled time during a run starts after it, an exception in a run releases the lock, a run of one ineligible product records it `failed`, and dashboard pages answer while a run is in progress

- [x] 4.7 Pass `UPGRADE_RUN_URL` into each product's session, naming the run's page and the product within it — verify tests that the composed URL reaches the session's environment, and that a deployment with no public URL passes an empty value

- [x] 4.8 Implement cancellation of the active run (D16): a registry of the run executing now and of the session it is waiting on, a request that ends that session's process group and stops the run before its next product, and the `canceled` product outcome and run state — verify tests with a fake pi that sleeps: the session and its child process are gone, the product and the run are recorded `canceled` with the transcript still stored, the run's later products never start, and a run requested after a canceled one runs normally

## 5. History

- [x] 5.1 Implement redaction (D10) — verify tests covering each secret, every token minted during the run, the decoded key and a single line of its body, repeated occurrences, a value inside a JSON string, and an unset or empty secret changing nothing
- [x] 5.2 Upload each product's files under `runs/<run-id>/<slug>/`. Redact the transcript, export the HTML from the redacted copy with `pi --export`, and upload the output, `result.json`, `body.md` and `change.patch` with correct content types — verify with a fake S3 that each outcome stores the files `product-upgrade-history` lists, and that a real `pi --export` of a fixture transcript produces HTML
- [x] 5.3 Write the run and product-result rows from redacted values — verify a Postgres-backed round trip of a result carrying every field

## 6. Dashboard

- [x] 6.1 Add the FastAPI app with Basic authentication and `/healthz` (D13) — verify tests: 401 without credentials and with a wrong password; with `DASHBOARD_PASSWORD` unset every page except `/healthz` is refused; `/healthz` answers 200
- [x] 6.2 Add the run history and run pages, with signed links that expire within one hour — verify `TestClient` tests with a fake S3: newest run first, a `would_open` product shows its description and patch, and links carry the expiry
- [x] 6.3 Add "Run now" and "Run one product" — verify tests: both are refused while a run is active, and product choices are the products eligible on `master`, with no run needed first
- [x] 6.4 Add the progress fragment and htmx polling every five seconds — verify a test that the fragment names the running product and its elapsed time, and lists the finished products' outcomes
- [x] 6.5 Show PR state from GitHub with a five-minute in-memory cache — verify tests with a fake GitHub: a merged PR shows as merged, a cached state is reused within five minutes, and an unreachable GitHub renders the page with the state unknown
- [x] 6.6 Stream the running session in the progress panel (D13): a byte-offset reader of pi's transcript, redacted steps in a terminal-style layout, and a console kept across refreshes that fetches only new steps — verify tests: opening returns the latest steps and the end offset, a refresh returns only new steps, a partial line waits, an oversized line is skipped with a note, a rewritten file restarts from its end, a minted token is redacted, and a `<script>` in a step arrives escaped
- [x] 6.7 Render the pull request description as sanitized Markdown in the browser (D13) — verify in a browser that its headings, tables and `<details>` sections render, and that no `<script>` element survives

- [x] 6.8 Render the patch as text rather than in a frame, and give each pane a control that opens it over the page — verify tests that the run page carries a patch element fetched from the signed link and one control per pane, and in a browser that a diff's lines are coloured, that expanding and closing a pane fetches nothing again, and that Escape closes it

- [x] 6.9 Give the running session's panel the same expand control, moving the panel itself so its poller and steps travel with it and carrying its scroll position across the move — verify a test that the terminals fragment carries the control, and in a browser that the log keeps its steps and its scroll position when opened and closed, that new steps still arrive while it is open, and that the set of running products is re-synced on close

- [x] 6.10 Add the cancel control to the active run's panel, behind a confirmation — verify tests: the progress fragment carries the control while a run is active and carries none otherwise, a cancel of the active run redirects with a message and marks the run, and a cancel naming a finished or unknown run is refused

- [x] 6.11 Key the history's refresh on the active run's id as well as on what is running, so that a run ending refreshes its row: its last product is recorded as finished before the run is, so neither the running products nor the active flag need change when it ends — verify a test that the progress fragment carries the run's id while it runs, still carries it in the window where the product has finished and the run has not, and empties it once the run has finished

## 7. Notifications

- [x] 7.1 Implement the noteworthy rule and compose the email (D14) — verify tests with a fake SMTP server: no email when everything is up to date, one email for a `would_open` product listing its target version, `needs_human` items listed for a draft, and no email when `NOTIFY_EMAIL` is unset or the run was interrupted
- [x] 7.2 Log a failed send, and leave all outcomes unchanged — verify a test where the fake SMTP server refuses the message

- [x] 7.3 Name the noteworthy products in the email subject, each with its outcome and the version it moves to, capped with a count of the rest — verify tests: a single `would_open` product and its target version in the subject, several noteworthy products named while an up-to-date one is not, and a run with more noteworthy products than the subject carries

## 8. Local end-to-end

- [x] 8.1 Run the built image locally against a local Postgres, a local S3 and an SMTP sink, in dry-run mode against the real inference endpoint. Request "Run one product" for `vaultwarden` — verify the dashboard shows the outcome and the transcript link opens, the email arrives when the outcome is noteworthy, and no stored object contains a minted token or the key

## 9. Operator tasks (manual)

- [x] 9.1 Register a GitHub App under the owner's account: no webhook, installable only on this account, and repository permissions Contents read and write, Pull requests read and write, and Metadata read, with nothing else. Generate a private key and record the App id — verify the App's settings page lists exactly those three permissions
- [x] 9.2 Install the App on `erikvanzijst/freepod` only ("Only select repositories") — verify the installation's settings page lists that one repository
- [x] 9.3 Create the branch ruleset: target all branches, exclude `refs/heads/upgrade/**`, and enable "Restrict creations", "Restrict updates" and "Restrict deletions". Create the tag ruleset: target all tags, with the same three rules. Give both a bypass list of only the Repository admin role, in "Always allow" mode — verify `gh api repos/erikvanzijst/freepod/rulesets/<id>` for each shows those conditions, rules and `bypass_mode` `always`, and that the owner can still push an empty commit straight to `master`
- [x] 9.4 Probe the rulesets with a read-write token. On the development machine, mint one with the service's token code and the downloaded key, then from a scratch clone: push `upgrade/probe` and open a PR from it, then try to merge that PR, push to `master`, push `nextcloud-34.0.4` with `--no-verify`, and push a tag `probe-0` — verify the first push and the PR succeed, and all four others are refused by GitHub; then close the PR and delete `upgrade/probe`
- [x] 9.5 Run `freepod init` in `ops/upgrader/` and commit `.freepod.json` — verify the file names the chosen hostname
- [x] 9.6 Stage the vars. Type the three secrets at the prompt (`freepod var set GITHUB_APP_PRIVATE_KEY --secret --stage`, pasting `base64 -w0` of the key file, and the same for `INFERENCE_API_KEY` and `DASHBOARD_PASSWORD`), never on the command line. Stage the plain vars, including `GITHUB_APP_ID`, in one command, leaving `UPGRADE_DRY_RUN` at its dry-run default — verify `freepod var list` shows every var, with the three secrets hidden
- [x] 9.7 Run `freepod deploy` from `ops/upgrader/` — verify `/healthz` answers 200 on the live URL, and `freepod log` shows the migrations applied and the server started, and the first run's products get past GitHub setup (none fails with "setting up GitHub access failed"), which shows the App's installation was found
- [x] 9.8 Probe the guards in the deployed container, calling the guard binaries directly with `freepod shell`: `gh pr merge 1`, `gh auth token`, and a path-less `git grep` in a scratch clone — verify all three are refused
- [x] 9.9 Request "Run one product" from the dashboard, then let the first nightly dry run complete — verify each product's result and transcript are in the dashboard, and an email arrives if any product would open a PR
- [x] 9.10 Once the dry runs are trusted, switch to real PRs with `freepod var set UPGRADE_DRY_RUN=0`, outside the nightly window — verify the next run that finds a release opens a PR authored by the App's bot user and labeled `product-upgrade`, and that CI runs on it

## 10. Documentation

- [x] 10.1 Write `ops/upgrader/README.md`: running locally (the local runner and the tests), building and deploying, the vars, and operations (switching modes, rotating the App's key, releasing a product blocked by a leftover `upgrade/*` branch, reading a run) — verify it links the specs and this change's design rather than restating them
- [x] 10.2 Add the service's entry to `AGENTS.md` per § Documentation Layering — verify it is a terse orientation plus links to the seven specs and the design
