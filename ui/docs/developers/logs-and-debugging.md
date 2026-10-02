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
```

Application output goes to stdout and the client's own messages to stderr, so `freepod log > app.log` captures only the application's output. Release numbers come from `freepod releases`.

When a release fails, `freepod deploy` prints the last lines of the failed container's output. `freepod log -r <release>` shows all of it.

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
| Requests fail, logs look normal | `freepod releases`: a failed release leaves the previous one running |
| Configuration seems wrong | `freepod shell env` shows the environment the application receives |
| Files seem missing | `freepod shell ls -la` shows what the image contains; see [Builds: What is uploaded](builds/index.md#what-is-uploaded) |
| Database errors | [PostgreSQL](storage/postgresql.mdx): read-only at 100 % of the allowance, connections refused at 150 % |
