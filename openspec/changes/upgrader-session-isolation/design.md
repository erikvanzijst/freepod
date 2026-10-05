## Context

See proposal.md (Why) for the threat. The relevant current state:

- **Users and processes.** The image runs as `node` (uid 1000). tini, uvicorn and every pi
  session run as `node`. The pod sets `shareProcessNamespace: true`, and the `ssh` sidecar
  runs as root. The `custom` chart gives the app container no `securityContext`, so a
  setuid `sudo` works.
- **What `session_env` actually protects.** It drops the secrets from the child's
  environment, but `/proc/<pid>/environ` of tini (pid 40) and uvicorn still holds them,
  and any process running as `node` can read them. Verified on the live pod on 2026-10-05:
  `GITHUB_APP_PRIVATE_KEY`, `AWS_SECRET_ACCESS_KEY`, `PGPASSWORD`, `DATABASE_URL`,
  `SMTP_PASS`.
- **Where the runner reads files the agent wrote.** `workspace/out/<slug>/*`, the
  transcript under `workspace/session/`, and the live tail in `live.py`. It reads the
  schema from the agent's clone too (`_schema(workspace)`).
- **How sessions are ended.** Cancel and timeout use `os.killpg` on the pi process group.
- **What the skill does on GitHub.** It pushes, creates the label, opens the PR, and waits
  for CI and fixes failures. A dry run already does everything except those steps, and
  writes `body.md`, `change.patch` and `meta.json` instead. This change makes that dry-run
  path the only path a session takes.
- **How the dashboard authenticates.** It trusts `X-Freepod-Email`. uvicorn binds
  `0.0.0.0:8080`, and a request from inside the pod never passes Traefik's header
  stripping. Verified: `curl localhost:8080/` gives 401, while the same request with an
  unlisted `X-Freepod-Email` gives 403, so the header is honored.

## Goals / Non-Goals

**Goals:**
- An injected session can damage only its own proposal: the patch, the description and
  `result.json`. The service validates all three before anything reaches GitHub.
- No credential that outlives the product is reachable from a session.

**Non-Goals:**
- **The inference API key.** pi needs it in its environment, so it remains exfiltrable.
  It reaches only the owner's inference endpoint.
- **The cluster SMTP relay,** which takes mail without credentials. That is a tenant-wide
  issue, tracked separately.
- **Resource abuse** by a session, such as a fork bomb or filling the disk.
- **The local runner's environment.** A developer's machine holds ambient credentials:
  `gh` auth, SSH keys, kube config. The local runner gives up real runs; dry runs there
  remain a trusted-operator tool, and its README says so.
- **CI follow-up.** No one waits on or fixes CI for an opened PR; the reviewer sees CI on
  the PR.

## Decisions

### D1: A second uid, entered through sudo

The image adds a system user `agent` (uid 1001, no login shell needed) and installs
`sudo`. The sudoers file `/etc/sudoers.d/upgrader` holds:

```
Defaults:node !env_reset, !secure_path, !use_pty, !lecture, !syslog
node ALL=(agent) NOPASSWD: ALL
```

`node` also joins the `agent` group, so it can hand the token file and the workspace to
that group alone. `use_pty` is off because Debian turns it on by default, and a pty would
come between pi and the stdout file the service hands it. `syslog` is off because the
container has no syslog.

`node` may run anything as `agent`. That is safe because `agent` is the less privileged
user: becoming it gains `node` nothing. `agent` has no sudoers entry at all. Turning off
`env_reset` and `secure_path` keeps the environment that `session_env` builds, including
`PATH` with the guards first, instead of sudo's defaults. `session_env` stays the single
place that decides what a session sees.

The service starts each session as `sudo -n -u agent -- pi …`. Everything else it does as
`agent` uses the same form: creating the session's clone, cleaning up, killing. One `Agent`
value (`upgrader/agent.py`) holds that prefix and always passes an explicit environment.
The test suite uses an `Agent` with an empty prefix, which means the service and the
session share a user. `tests/test_isolation.py` covers the real user in the image.

*Alternatives considered:*

- **A separate pod or Job per session.** This would be the strongest isolation, but a
  `custom` deployment is one container with no Kubernetes API access.
- **Starting as root and dropping to two users.** The service would keep `CAP_SETUID`, or
  run as root, for the life of the pod. That is a larger attack surface than one setuid
  binary with a single rule.
- **`hidepid=2` on `/proc`.** This needs a mount privilege the container does not have.
  It also leaves the files and signals problem open.
- **`prctl(PR_SET_DUMPABLE, 0)` in uvicorn.** This cannot cover tini, whose environment
  holds the same secrets.

### D2: Workspace layout and ownership

```
<workdir>/<slug>-XXXX/        node:agent 1770  sticky: the session can add, not replace
├── runner/                   node       0700  the service's own: its clone, stdout, renders
│   └── freepod/                               the service's clone of master
├── agent/                    node:agent 2770  PI_CODING_AGENT_DIR; models.json (0644) by the
│                                              service, pi's auth.json by the session
├── session/                  node:agent 2770  pi's --session-dir
├── out/                      node:agent 2770  UPGRADE_OUT_DIR
└── freepod/                  agent            the session's clone, made with sudo -u agent git clone
```

- **The shared directories belong to the service.** The session fills them but cannot
  swap one for a link, and the sticky root keeps it from replacing anything the service
  created. All of them exist before any process of the session user starts. pi writes
  `auth.json` into its agent directory, so that directory is shared rather than read-only.
- **Two clones.** The service clones first and records the commit for the dashboard. The
  session clones `master` as `agent`, and the skill resets to `origin/master` anyway, so
  the two can differ by whatever merged in between. Both are shallow.
- **The service's clone** supplies `result.schema.json` and is where the patch is applied.
  The session cannot read or write it.
- **The token file** moves to `<state>/tokens/<slug>`, in a directory owned by `node:agent`
  with mode `0750`. The file itself is `node:agent`, mode `0640`, so the session can read
  it but not replace it. The `upgrader` group trick is unnecessary: `agent`'s primary
  group serves.
- **Cleanup.** As `agent`, the service makes every directory `agent` owns writable and
  deletes everything `agent` owns. Then it removes the rest with `shutil.rmtree`. This
  also handles directories the session made unwritable.

### D3: Reading untrusted files: openat walk plus an owner check

One helper, `read_untrusted(root, relpath, max_bytes)`, opens each path component with
`O_NOFOLLOW` and opens directories with `O_DIRECTORY`, starting from a descriptor on the
workspace. It then `fstat`s the final file and requires `S_ISREG` and `st_uid == agent`.
Anything else counts as missing.

- **Why the owner check.** It closes the hard-link variant: a link to a file `node` owns
  keeps `node` as its owner. With the check, the service only ever reads bytes `agent`
  could have written.
- **Where it is used.** `_store_files`, judging the result, the proposal's files, the
  transcript, and `live.py`'s tail. Finding the transcript walks `session/` the same way,
  with `os.scandir` on a descriptor. `live.py` opens the transcript through the helper on
  every poll, so a file swapped between polls is not followed either.

*Alternative considered:* reading through `sudo -u agent cat`. This is equally safe, but it
costs a process per read, and the live tail polls.

### D4: The service publishes; the session proposes

For a `would_open` result, the service does the following in its own clone, as `node`:

1. **Check the patch.**
   - Fetch `master` and `git am` the patch onto it, on the branch `upgrade/<slug>-<target>`,
     with hooks off. The skill resets to `origin/master` at its start, so `master` as it is
     now is the base the session worked from, give or take a merge.
   - `git am` is the check: it applies a multi-commit mbox the way the commits were made,
     where `git apply --check` on the whole file would trip over a second commit touching
     the same lines.
   - Then `git diff --raw --no-renames base..HEAD` lists what changed. Every path must be
     `products/catalog/<slug>.yaml` or start with `products/<slug>/`, and no entry may have
     mode `120000` (symlink) or `160000` (gitlink). `git am` already refuses paths with
     `..` or inside `.git`.
2. **Check the metadata.**
   - The branch is `upgrade/<slug>-<target_version>`, and
     `git check-ref-format --branch` accepts it.
   - The title matches `^[^\n]{1,200}: Upgrade to <re.escape(target)>$`.
   - `body.md` is at most 65,536 characters.
   - The skill's sanitization rules:
     - no match of `github\.com/[^ ]+/(pull|issues)/[0-9]+` anywhere;
     - no `@` outside backticks. After removing fenced blocks and code spans, nothing may
       match `(?<![\w`])@[A-Za-z0-9]`, which exempts email addresses.
3. **Author as the bot.** `git rebase --force-rebase --exec 'git commit --amend --no-edit
   --reset-author'`, with `GIT_AUTHOR_*` and `GIT_COMMITTER_*` set to the bot.
4. **Publish.**
   - Mint a write token.
   - `git ls-remote` refuses an existing branch. Then push with
     `--force-with-lease=<ref>:`, which also refuses one that appeared in between. The
     explicit check exists because git skips the lease when the push would change nothing.
   - The token reaches git through `GIT_CONFIG_COUNT` as an `http.extraHeader`, never in
     argv, with the credential helper cleared.
   - Redact the title and body as stored files are redacted. Create the label if missing,
     open the PR, and label it, all through `httpx` with the same token. A failed label is
     logged, not fatal: the PR exists by then.

Steps 1–2 run when the result is judged, in both modes. A refusal therefore gets the
existing repair turn, and a dry run surfaces it too. Steps 3–4 run only in a real run.
Their failures, such as a push rejected because the branch exists or a network error,
record `failed`.

**The result contract.** It moves to `schema_version: 2`: `opened` leaves the session's
`status` enum, and `pr_url` leaves the object. `meta.json` shrinks to `{title}`, plus
`would_skip` in a dry run. The service fixes the labels, base and branch itself, so the
session has no say over them. The DB row's `outcome`/`pr_url`/`branch` columns are
unchanged, so the dashboard and notifications need no change.

*Alternatives considered:*

- **Pushing the session's branch by fetching from its clone.** Any git command the service
  runs against a repository the session controls runs under the session's
  `.git/config`, which means `core.fsmonitor`, hooks, `uploadpack.*` and similar. That is
  code execution as `node`. Applying `change.patch` treats the patch as data only, and
  makes the PR exactly the patch the dashboard shows.
- **Keeping writes in the session, with a short-lived write token.** The token would still
  be exfiltrable for an hour, and the session would decide what gets pushed.
- **A CI follow-up turn,** where the service resumes the session with failing check
  output. Deferred: it adds a polling loop and a third turn. The session already runs the
  lint and chart tests locally.

### D5: Termination by uid

`_terminate` becomes `sudo -n -u agent kill -TERM -1`, then a 10 s grace period, then
`kill -KILL -1`. This replaces `killpg`, because `node` cannot signal `agent`'s processes,
and the uid-wide kill catches anything that called `setsid`. Only one session runs at a
time (product-upgrade-runs), so "every process of `agent`" is exactly the session.
`Cancellation.request` calls the same function.

The sudo process stays the Popen child. It exits when pi dies, so `process.wait()` still
works, and tini's subreaper collects any orphans.

### D6: The dashboard refuses local peers

At startup, `web.py` collects the pod's own addresses: loopback, plus every address from
`socket.getaddrinfo(socket.gethostname())` and from the interfaces. A dependency then
refuses any non-`/healthz` request whose `request.client.host` is in that set, with a 403,
before the email check. Traefik and the kubelet connect from other addresses.

*Alternative considered:* verifying a signed assertion from app-auth. `X-Freepod-Jwt` is
reserved but not shipped. When it ships, it would replace this check.

### D7: The guards and the hook simplify

- **`bin/gh`.** `pr create` and `label create` are refused in every mode, and the
  `dry_run` helper goes.
- **`hooks/pre-push`.** It refuses every push, with a message saying the service
  publishes. The guards remain conveniences, as before. The real bound is the read-only
  token.

### D8: Deploy ordering

The skill and the schema are read from `master` at run time. The new runner rejects a v1
result, and the old runner rejects a v2 result. So:

1. Merge the PR, with the skill, the schema and the service.
2. Run `freepod deploy` outside the nightly window, the same day.
3. Run one dry run of a single product, then one real run, before the next night.

## Risks / Trade-offs

- **An `agent` session reads the read-only token and uses it elsewhere.** It is one hour,
  read-only, on a public repository. Accepted.
- **The publish checks reject a legitimate change**, such as a chart change that also
  needs `api/tests/test_chart_release_label_contract.py` edited (the `DATASTORES` list).
  → The patch is refused with a reason naming the path. The skill already says to
  escalate such cases. This change makes it say: propose the in-scope part as a draft and
  list the out-of-scope edit under *Needs human review*.
- **`!env_reset` lets the service's environment through sudo.** Only what `session_env`
  passes reaches the session. The risk is a future caller of `sudo -u agent` that passes
  `os.environ` unfiltered. → Route every call through one `as_agent()` helper that
  requires an explicit env, and test that the private key is absent.
- **`git am` and `git apply` have had parser CVEs.** The service pins Debian's git and
  processes only patches below a size limit (1 MiB). A parser compromise would run as
  `node`, which is today's exposure for every session.
- **The session can no longer react to CI.** → Accepted for now. See Non-Goals and the
  D4 alternative.

## Migration Plan

Follow D8. Rollback means redeploying the previous image and reverting the skill and schema
commit on `master`, together. Neither involves data migration. After deploying, verify
from `freepod shell`:

- `sudo -u agent cat /proc/$(pgrep -x tini)/environ` is refused, and the same holds for uvicorn.
- `sudo -u agent curl -s -o /dev/null -w '%{http_code}' -H 'X-Freepod-Email: <allowed>'
  localhost:8080/` gives 403.
