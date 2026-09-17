## Why

Every curated product pins an upstream version, and nothing notices when upstream moves
on. The upgrade-product skill now does that job for one product: detect a release, review
what changed in how upstream deploys it, and open one reviewed pull request. Sixteen graded
dry runs with a local model (pi 0.85.1, `qwen3.8-27b-q4`) show it passing the hardest
scenarios in the catalog. What it lacks is somewhere to run. Today a human starts it by
hand from a development container, reads its free-text report, and the evidence of each
run (the session, the would-be pull request) stays in a local, gitignored directory.

This change gives the skill that home: a small internal service, deployed as the owner's
own Freepod `custom` deployment, that runs the skill for every curated product each night
and keeps a browsable history of what it did and why.

## What Changes

- **The skill moves into the repository** at `products/UPGRADING/SKILL.md`, as the
  experiment's decision log (D6) planned. The Immich and Nextcloud READMEs gain the
  "Upstream references" additions that the runs produced.
- **The skill writes a machine-readable `result.json`** for its product, in real runs and
  dry runs, alongside its prose report. The service reads that file and never parses prose.
- **A new service in `ops/upgrader/`**, built from its own root `Dockerfile` and deployed
  manually with `freepod deploy` from that directory. One process serves a web dashboard
  and executes the runs on a background thread.
- **A nightly run over the catalog**, at 03:00 Europe/Brussels by default, plus on-demand
  runs of the whole catalog or of one product. Products run one after another, each in a
  fresh agent session and a fresh clone of `master`, under a per-product timeout.
- **The skill is fetched, not baked in.** Each session reads the skill from its own clone
  of `master`, and the service records which commit that was, so a skill change ships by
  merging it.
- **A run history**, indexed in the deployment's Postgres and filed in its bucket. For each
  product it keeps the outcome, the versions, the PR link, timings and token counts, plus
  the session transcript, its HTML rendering, the PR description, the patch and the agent's
  output. Nothing is ever pruned. Secret values are redacted before anything is stored.
- **A dashboard** behind HTTP Basic auth. It shows the run history, per-product results
  (including the would-be PRs of dry runs), live progress, each PR's current GitHub state,
  and "Run now" and "Run one product" buttons.
- **Email** through the platform's shared SMTP relay, sent only when a run opens a PR
  (or would, in a dry run) or a product fails.
- **A GitHub App** acts for the service. It is installed on this repository only, with
  write access to contents and pull requests and nothing else, and the service mints
  one-hour tokens from its key. Rulesets let it create and update only `upgrade/*`
  branches and no tags, so it cannot merge, push to `master`, or tag a release. A `gh`
  guard and a pre-push hook keep the agent's normal path to reading and opening PRs.
- **A `git` guard** refuses a `git grep`, or a pickaxe or patch `git log`, that names no
  path. In the blobless upstream clones the skill makes, such a command fetches every
  file one at a time: one took 8.5 minutes in one dry run and another ran over 12 minutes
  before it was killed.
- **Dry run first.** The service defaults to `UPGRADE_DRY_RUN=1`: sessions get read-only
  tokens, the guards refuse writes, and the dashboard shows the PRs it would have opened.
  The owner switches to real PRs with one `freepod var set`.
- The prototype loop `var/upgrade_products.sh` moves into `ops/upgrader/` as the local
  runner.

No platform component changes. The service is a Freepod tenant like any other and uses
only what every `custom` deployment is given.

## Capabilities

### New Capabilities
- `product-upgrade-skill`: the skill as a repository artifact. It covers where the skill
  lives, the rule of one named product per session, the dry-run boundary, and the
  `result.json` contract a runner consumes.
- `product-upgrade-service`: the service as a Freepod deployment. It covers the image and
  its pinned tooling, the one process that serves the dashboard and executes runs, the
  configuration surface, and how the agent's model is configured.
- `product-upgrade-runs`: what a run is. It covers when a run starts, which products it
  covers, how each product is executed and bounded, why at most one run is active, and
  what becomes of a run that a restart cuts short.
- `product-upgrade-history`: what is recorded about every run and product, where it is
  kept and for how long, and the rule that no secret value is stored.
- `product-upgrade-dashboard`: the authenticated web interface over the history, with the
  run triggers, live progress and PR state.
- `product-upgrade-notifications`: which runs send an email, to whom, and through what.
- `product-upgrade-guardrails`: the GitHub App the agent acts as, the rulesets that
  confine it, the command guards that keep the normal path inside those limits
  (including what a dry run guarantees), and the guard that keeps history searches
  path-limited.

### Modified Capabilities

None. The catalog's `upstream` block (`product-catalog-format`) is consumed as specified.

## Impact

- **New:** `ops/upgrader/`. It holds the `Dockerfile`, `.freepod.json`, the dashboard
  and scheduler (Python, managed with uv), the Alembic
  migrations, the GitHub App token minting, the `gh` and `git` guards and the push hook,
  the tests, a README, and the local runner moved from `var/upgrade_products.sh`.
- **New in git:** `products/UPGRADING/SKILL.md`, from the gitignored
  `var/upgrade_product.md`, extended with the `result.json` contract.
- **Product READMEs:** `products/immich/README.md` and `products/nextcloud/README.md`
  gain the additions in `var/proposed_readme_changes.patch`.
- **GitHub (operator):** a GitHub App registered under the owner's account and installed
  on this repository, and a branch ruleset and a tag ruleset. The `product-upgrade` label is
  created by the first real run.
- **Freepod (operator):** one new `custom` deployment on the owner's account, with its
  database, its bucket, and its vars and secrets.
- **Docs:** an `AGENTS.md` entry per § Documentation Layering, and
  `ops/upgrader/README.md` for running, deploying and operating the service.
- **Unchanged:** `api/`, `ui/`, `cli/`, `tf/`, the product charts and the catalog files.
