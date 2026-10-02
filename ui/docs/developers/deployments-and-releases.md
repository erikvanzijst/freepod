---
title: Deployments and releases
---

# Deployments and releases

## Creating a deployment

The first `freepod deploy` in a project creates its deployment, records it in `.freepod.json`, and serves a placeholder page on the hostname until the first build is released. Release 1 is that placeholder.

### Starting over with `--recreate`

`freepod deploy --recreate` ignores the deployment recorded in `.freepod.json`, creates a new deployment with the settings in the file, and records the new one. The new deployment starts with an empty database, an empty bucket and no variables.

The previously recorded deployment is not changed or deleted. Use `--recreate` when:

- the recorded deployment no longer exists, for example because it was deleted from the dashboard; `freepod deploy` reports this and suggests `--recreate`;
- you want a second, independent deployment of the same source. Change `hostname` in `.freepod.json` first: a hostname held by the old deployment is refused.

## Releasing

| Command | New build | Applies |
| --- | --- | --- |
| `freepod deploy` | Yes | Source, settings in `.freepod.json`, staged vars |
| `freepod deploy --no-build` | No | Settings in `.freepod.json`, staged vars |
| `freepod var set`, `freepod var rm` | No | The changed vars, staged vars |

Each of these creates one numbered release. One release runs at a time per deployment: a command that starts a release while another is queued or running fails, and can be retried when the first one finishes. `freepod var set --stage` and `freepod var rm --stage` save changes without starting a release.

A release replaces the running container. The sequence is described under [Runtime contract: Releases](runtime.mdx#releases):

- The previous version serves traffic until the new container passes the [health check](runtime.mdx#health-check).
- Connections still open to the previous container, such as WebSockets or streaming responses, are closed when it stops.

## Failed releases

A release fails when the new container does not pass the health check within 5 minutes, for example because it exits at startup or does not listen on `$PORT`. The previous release keeps serving traffic.

`freepod deploy` prints the platform's error and the last lines of the failed container's output. The full output of any release, including a failed one, is available with `freepod log -r <release>`.

## Listing releases

```bash
freepod releases
```

```
   RELEASE  STATUS     CREATED           DURATION  IMAGE
*  3        succeeded  2026-10-02 11:41  19s       1@sha256:1630d8499286…
   2        succeeded  2026-10-02 11:19  25s       1@sha256:1630d8499286…
   1        succeeded  2026-10-02 11:17  32s       -
* the release this deployment is running.
```

The release marked `*` is the one serving traffic. After a failed release, that is an earlier one.

| Status | Meaning |
| --- | --- |
| `queued` | Waiting to start |
| `in_flight` | Rolling out |
| `succeeded` | Rolled out |
| `failed` | Did not pass the health check in time; see [Failed releases](#failed-releases) |
| `abandoned` | Interrupted by a platform fault |

`--all` lists every release; `--verbose` prints full image references.

## Rolling back

There is no rollback command. Check out the previous version of the source and run `freepod deploy`.

## Deleting a deployment

```bash
freepod delete
```

deletes the project's deployment after asking for confirmation, and waits until the deletion has finished. `--yes` skips the confirmation, and is required when there is no terminal. `--no-wait` returns once the deletion has started.

A deployment can also be deleted from the [dashboard](app:/).

Deleting a deployment:

- stops the application and frees its hostname once the deletion has finished;
- deletes its [PostgreSQL database](storage/postgresql.mdx) and [object storage bucket](storage/object-storage.mdx). Access ends immediately; the data is destroyed after one day and cannot be recovered;
- deletes its variables;
- ends usage metering for it.

**Back up any data you need before deleting.** Freepod does not restore deleted deployments.

`.freepod.json` keeps its settings. The next `freepod deploy` in the project creates a new, empty deployment with the same hostname.

## Exit codes

`freepod deploy` and the other commands exit with:

| Code | Meaning |
| --- | --- |
| `0` | Success |
| `1` | Other error |
| `2` | Invalid usage |
| `3` | Not signed in |
| `4` | Build failed |
| `5` | Release failed or timed out |
