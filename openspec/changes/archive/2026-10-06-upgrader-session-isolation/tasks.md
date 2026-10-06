## 1. Image and privilege separation

- [x] 1.1 In `ops/upgrader/Dockerfile`, add the `agent` user (uid 1001), install pinned `sudo`, and add `/etc/sudoers.d/upgrader` from D1 (mode 0440). Verify with `docker run … sudo -n -u agent id`, which prints uid 1001. Then, running as `agent`, `sudo -n true` must fail.
- [x] 1.2 Add an `as_agent(cmd, env, **popen)` helper (built as the `Agent` value in `upgrader/agent.py`). It always passes an explicit env and prefixes `sudo -n -u agent --`. Add a unit test asserting that the argv starts with sudo and that no inherited `os.environ` value leaks through. Add a second test, run under `sudo -u agent env` inside the image, showing `PATH` begins with the guards and `GITHUB_APP_PRIVATE_KEY` is absent.
- [x] 1.3 Find out whether pi writes into `PI_CODING_AGENT_DIR`: run `strace -f -e trace=openat` or check the dir's mtime after a `fake_pi` run in the image. Then place `models.json` per D2. Verify a session starts as `agent` and reads the model config.

## 2. Workspace, clones and cleanup

- [x] 2.1 Restructure `execute_product` to the D2 layout. The service makes its own clone in `runner/freepod`, and the session's clone of `master` is made as `agent`. Assert the owners and modes of `runner/`, `freepod/` and the shared directories (in `tests/test_isolation.py`).
- [x] 2.2 Move the token file to `<state>/tokens/<slug>`, with the directory `node:agent 0750` and the file `0640`. Always mint `READ_ONLY` for sessions. Test that a session-mode `TokenFile` never requests a write permission, in either mode.
- [x] 2.3 Clean up by running `as_agent(rm -rf …)` on the agent-owned subtrees, then `shutil.rmtree`. Add a test where `fake_pi` leaves a `0500` directory with files in it. After the product, the workspace must be gone.

## 3. Untrusted reads

- [x] 3.1 Implement `read_untrusted(root_fd, relpath, max_bytes)` per D3: an `O_NOFOLLOW` walk, `S_ISREG`, `st_uid == agent`, and a size cap. Unit tests must cover a symlinked final component, a symlinked intermediate directory, a hard link to a `node`-owned file, a FIFO, and an oversized file. Each must be treated as missing.
- [x] 3.2 Route `_store_files`, `_result_problem` and `_transcript` through the helper. Make `live.py`'s tail keep one descriptor opened through the helper. Add a test where `fake_pi` makes `body.md` a symlink to a file holding a fake secret: nothing containing that secret is stored.
- [x] 3.3 Take `result.schema.json` from the service's clone. Add a test where `fake_pi` rewrites the schema in its clone: an `opened` result is still rejected.

## 4. Result contract v2 and publish checks

- [x] 4.1 Update `products/UPGRADING/result.schema.json` to `schema_version` 2: drop `opened` and `pr_url`, keep `branch` required for `would_open` and `would_skip`. Update `result.py`, its CLI summary, and the `test_result`/`test_runner` fixtures. `uv run pytest` must pass.
- [x] 4.2 Implement the proposal checks from D4 steps 1–2 in a `proposal.py`: patch paths, modes, `git apply --check` in the service clone, branch format, title, body size and sanitization. Make `_result_problem` return their reason so that the repair turn handles a refusal. Table-driven tests must cover every refusal in the `product-upgrade-runs` spec, plus an accepted tag-only patch.

## 5. Publishing

- [x] 5.1 Add `App.create_label_if_missing` and `App.open_pull_request` in `github.py`, with mocked-httpx tests for draft and ready PRs and for an existing label.
- [x] 5.2 Implement `publish()` per D4 steps 3–4. It applies the patch with `git am`, resets authorship to the bot identity, and pushes with the token in `GIT_CONFIG_*` env only, never with `--force`. Then it creates the label and opens the PR. A test against a local bare repo standing in for the remote must assert:
  - the pushed commit's author is the bot, even when the patch names someone else;
  - the token never appears in any argv;
  - pushing to an existing branch records `failed`.
- [x] 5.3 Wire `publish()` into `execute_product` for real runs with an accepted `would_open`. It records `opened` with `pr_url`, `branch` and `draft`, or `failed` with GitHub's reason. Add a runner test for each path. A dry-run test asserts that `publish()` is never called.

## 6. Termination

- [x] 6.1 Replace `_terminate` and `Cancellation.request`'s `killpg` with the uid-wide kill from D5. Add an integration test in the image: `fake_pi` spawns a `setsid sleep 1000`, and after a timeout or cancel no `agent` process remains (`pgrep -u agent` is empty).

## 7. Guards, skill and local runner

- [x] 7.1 Make `bin/gh` refuse `pr create` and `label create` in every mode, and make `hooks/pre-push` refuse every push. Update `test_guards.py` to cover both modes.
- [x] 7.2 Rewrite `products/UPGRADING/SKILL.md` for the propose-only flow:
  - drop `gh auth setup-git`, step 8's commands and the CI wait;
  - write `body.md`, `change.patch` and `meta.json` for `would_open` in both modes;
  - keep the duplicate-check difference between modes;
  - add the rule that a needed edit outside the product's paths goes under *Needs human review*;
  - update the result table, the examples and the run report line.

  Verify with one `upgrade_products.sh <slug>` dry run that ends `would_open` and passes `python -m upgrader.result`.
- [x] 7.3 Make `upgrade_products.sh` refuse `UPGRADE_DRY_RUN=0` with a message pointing to the service, and validate the proposal with the same checks (`python -m upgrader.proposal`). Verify that `UPGRADE_DRY_RUN=0 ./upgrade_products.sh x` exits non-zero before starting pi.

## 8. Dashboard

- [x] 8.1 Add the local-peer refusal from D6 to `web.py` as a dependency on every route except `/healthz`. In `test_web.py`, a request whose client is `127.0.0.1` or the pod's address with an allowed email must get 403, `/healthz` from loopback must get 200, and a request from another address keeps today's behavior.

## 9. Docs and rollout

- [x] 9.1 Update `ops/upgrader/README.md`:
  - the `agent` user;
  - the service publishes PRs;
  - the local runner is dry-run only, with its ambient-credentials caveat;
  - `freepod shell` probes now use `sudo -u agent`.

  Mark design D8 of `product-upgrade-service` as superseded where it says the private key is within the agent's reach.
- [x] 9.2 Run `uv run pytest` in `ops/upgrader` and `openspec validate upgrader-session-isolation --strict`. Both must pass.
- [x] 9.3 Roll out per design D8, outside the nightly window: merge, `freepod deploy`, then run the post-deploy probes from the Migration Plan. Both must be refused.
- [x] 9.4 Run one real run on a single product that has an eligible release. The PR must be authored by the bot, labeled, and its diff must equal the stored `change.patch`.
