## Why

The upgrade agent reads untrusted upstream content (release notes, changelogs, READMEs,
compose files) and runs shell commands, so a prompt injection can make it do anything its
shell can do. Today that shell runs as the same user as the service. On the live pod,
2026-10-05, that user can read `/proc/<tini>/environ`, which holds
`GITHUB_APP_PRIVATE_KEY`, `AWS_SECRET_ACCESS_KEY`, `PGPASSWORD`, `DATABASE_URL` and
`SMTP_PASS`. The pod's egress is open to the internet, and DNS lookups would leak data
even if it were not.

Design D8 of `product-upgrade-service` accepted that the agent could reach the private key,
on the grounds that the rulesets bound what it can do. It did not account for three things:

- The key never expires, and it mints write tokens even while the service is in dry run.
- The bucket and database credentials let an injected session rewrite its own transcript
  and run history, which is the audit trail a reviewer relies on.
- The dashboard trusts `X-Freepod-Email` on any connection. From inside the pod, a request
  to `localhost:8080` skips Traefik's header stripping, so the agent can start and cancel
  runs and read every stored file.

## What Changes

- **Sessions run as their own unprivileged user.** pi and everything it starts run as
  `agent`, not as `node`. A session can then no longer read the service's environment or
  files, or signal its processes.
- **Sessions never write to GitHub.** **BREAKING** for the skill contract. Every session,
  real or dry, only proposes. It commits locally and writes `result.json`, `body.md`,
  `change.patch` and `meta.json`. In a real run the service validates that proposal, and
  then pushes `upgrade/<slug>-<target>` and opens the PR itself.
  - The service builds the pushed branch from `change.patch`, applied to its own clone, so
    the PR is exactly the patch the dashboard shows.
  - The patch may touch only that product's paths. The PR title, label and authorship are
    fixed by the service. The description must pass the changelog-sanitization checks.
  - A proposal that fails validation gets the existing single repair turn.
- **Sessions only ever hold a read-only installation token.** The write token is minted
  by the service at publish time and never enters a session's reach.
- **The service treats the session's files as hostile.** It reads them without following
  symbolic links, and only when the session's user owns them. It validates results against
  its own copy of `result.schema.json`, not the one in the session's clone.
- **Cancel and timeout act on the session's user.** They end every process of that user,
  including processes that left the session's process group.
- **The dashboard refuses requests from inside its own pod**, whatever headers they
  carry. `/healthz` stays open.
- **The skill changes.**
  - It drops its push, label and PR steps, and the CI wait-and-fix loop.
  - Result `schema_version` becomes `2`. A session no longer writes `opened` or `pr_url`.
  - `meta.json` is required whenever the status is `would_open`, in real and dry runs alike.
- **The local runner (`upgrade_products.sh`) only does dry runs.** Real pull requests come
  only from the service.

Considered and left out:

- **An egress allowlist.** DNS through kube-dns would still leak data, and the agent needs
  GitHub, the registries and the inference endpoint anyway.
- **`PR_SET_DUMPABLE` in uvicorn.** It does not protect tini, whose environment holds the
  same secrets, and the separate user makes it redundant.
- **Waiting for CI in the service.** The session already runs the lint and chart tests
  before proposing.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `product-upgrade-guardrails`:
  - The session runs as a separate user that can read no secret of the service.
  - Sessions push nothing and hold only read-only tokens, in every mode.
  - The `gh` guard refuses `pr create` and `label create` in every mode.
  - The private key is out of the agent's reach.
- `product-upgrade-runs`:
  - In a real run, the service publishes a `would_open` proposal after validating it, and
    a validation failure gets the repair turn.
  - Results are validated against the service's own schema.
  - Session files are read without following links.
  - Termination covers every process of the session's user.
- `product-upgrade-skill`:
  - No session writes to GitHub.
  - Result schema v2: no `opened` and no `pr_url`; `meta.json` is required for
    `would_open`.
  - A real run still stops at a duplicate check, and a dry run still carries on past it.
- `product-upgrade-dashboard`:
  - Requests from inside the pod are refused.

## Impact

- `ops/upgrader/`:
  - `Dockerfile`: the `agent` user, `sudo`, and the sudoers rule.
  - `runner.py`: session launch, termination, workspace layout and cleanup, plus a new
    publish step.
  - `github.py`: create the label, open the PR, push with a token.
  - `result.py`: schema v2 and the publish checks.
  - `live.py` and the store upload: reads that do not follow links.
  - `web.py`: refuse local requests.
  - `bin/gh` and `hooks/pre-push`: refuse every write.
  - `upgrade_products.sh`: dry runs only.
  - Tests and `README.md` throughout.
- `products/UPGRADING/SKILL.md` and `result.schema.json`. These are read from `master` at
  run time, so they must merge in the same window as the image deploys (see design).
- The DB keeps `outcome = opened` and `pr_url`, now written by the service. The dashboard
  and notifications are unchanged.
- No platform change: the `custom` chart sets no `securityContext`, so `sudo` works in the
  app container.
- Not covered here:
  - The unauthenticated cluster SMTP relay, which is tracked separately as a tenant-wide
    issue.
  - The inference API key, which pi needs and which therefore stays readable by the
    session.
