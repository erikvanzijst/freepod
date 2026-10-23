---
title: Logs and debugging
---

# Logs and debugging

## Logs

Everything the application writes to stdout and stderr is collected and kept for 14 days.

```bash
freepod log              # the most recent 200 lines
freepod log -n 1000      # the most recent 1000 lines (at most 5000)
freepod log -f           # stream output, across releases
freepod log -r 4         # output of release 4, including a failed one
freepod log -t           # prefix each line with its timestamp
freepod log --since 2h   # only the last two hours (30s, 15m, 2h, 3d; at most -n lines)
freepod log --json       # one JSON object per line: ts, line, release
```

Application output goes to stdout and the client's own messages to stderr, so `freepod log > app.log` captures only the application's output. Release numbers come from `freepod releases`.

`--since` returns at most `-n` lines (200 by default), the newest in the window. It reaches back at most 14 days.

When a release fails, `freepod deploy` prints the last lines of the failed container's output. `freepod log -r <release>` shows all of it.

## HTTP requests

`freepod log --http` prints the requests that reached the deployment, one per line, in Combined Log Format:

```bash
freepod log --http                  # the most recent 200 requests
freepod log --http -f               # stream requests as they arrive
freepod log --http --since 1h -n 5000
freepod log --http --json           # one JSONL record per request
```

```
203.0.113.7 - - [23/Oct/2026:12:50:48 +0000] "GET /index.html HTTP/2.0" 200 512 "https://example.org/" "Mozilla/5.0 (X11; Linux x86_64)"
```

The fields are the client address, the time the request started (UTC), the request line, the status, the response size in bytes, the referer and the user agent. `-t` prefixes the time the request was logged, after it finished.

`--json` records also carry `host` (useful when the deployment serves several hostnames) and `duration_ms`:

```json
{"ts":"1792759848155836101","time":"2026-10-23T12:50:48.123456789Z","host":"myapp.freepod.app","remote_addr":"203.0.113.7","method":"GET","path":"/index.html","protocol":"HTTP/2.0","status":200,"bytes":512,"duration_ms":32.412,"referer":"https://example.org/","user_agent":"Mozilla/5.0 (X11; Linux x86_64)"}
```

`referer` and `user_agent` are `null` when the request carried none. Requests are routed to the deployment, not to a release, so `--http` does not combine with `-r`. HTTP requests are kept for 14 days.

## SSH key

`freepod shell`, `freepod cp`, `freepod db shell` and `freepod db proxy` connect over SSH and need `ssh` (and `sftp` for `cp`) on your machine, and an SSH key registered on your account:

```bash
freepod key add                    # generate a key for this machine and register it
freepod key add ~/.ssh/id_ed25519.pub   # or register an existing public key
freepod key list                   # registered keys; this machine's is marked *
freepod key rm SHA256:...          # revoke a key by fingerprint
```

A key belongs to your account and works for all your deployments. Keys can also be managed in the dashboard under **Settings → SSH keys**.

## Shell

```bash
freepod shell                          # interactive shell in the application container
freepod shell env                      # run one command
freepod shell 'ps aux | head'          # quote pipes to run them remotely
freepod shell cat app.log > app.log    # output streams to the local terminal
freepod shell -t top                   # allocate a tty for full-screen programs
```

- The shell starts in the application's working directory, with the application's environment.
- The exit code is the remote command's. `127` means the image does not contain the command. `255` can also mean `ssh` itself failed.
- The shell works while the application is failing its readiness check, as long as the container is running.
- Changes made in the container are lost at the next restart or release. Fix problems in the source and redeploy.

## Copying files

```bash
freepod cp report.csv :/app/report.csv     # local to deployment
freepod cp :/app/out.log ./out.log         # deployment to local
freepod cp ./assets :/app/assets           # directories are copied recursively
```

The deployment side is marked with a leading `:`. A relative remote path is relative to the application's working directory. File modes are kept; owners and timestamps are not. Nothing needs to be installed in the image.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `freepod deploy` exits with code `4` | The build log printed by `deploy`; `freepod builds` |
| `freepod deploy` exits with code `5` | The output printed by `deploy`; `freepod log -r <release>`. Usually the server exits at startup or does not listen on `0.0.0.0:$PORT`. |
| Requests fail, logs look normal | `freepod log --http` shows whether requests reach the application and what status they get; `freepod releases`: a failed release leaves the previous one running |
| Configuration seems wrong | `freepod shell env` shows the environment the application receives |
| Files seem missing | `freepod shell ls -la` shows what the image contains; see [Builds: What is uploaded](builds/index.md#what-is-uploaded) |
| Database errors | [PostgreSQL](storage/postgresql.mdx): read-only at 100 % of the allowance, connections refused at 150 % |
