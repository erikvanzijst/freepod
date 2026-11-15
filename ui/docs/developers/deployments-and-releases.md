---
title: Deployments and releases
---

# Deployments and releases

## Creating a deployment

`freepod init` creates a project's deployment, records it in `.freepod.json`, and serves a placeholder page on the hostname until the first build is released. Release 1 is that placeholder. `init` returns while the deployment is still being set up; [variables](variables-and-secrets.md) can be set right away, and the first `freepod deploy` waits for it.

### Linking an existing deployment

`freepod link <name>` points a project at a deployment you already have, by its name or id. Use it in a fresh clone of a project whose `.freepod.json` is not committed, or to recover a lost file: the new file gets back the settings the old one managed. Without a name, on a terminal, `link` lists your deployments to pick from.

### Starting over

`freepod init --force` creates a new deployment and points `.freepod.json` at it, keeping the file's settings. The new deployment starts with an empty database, an empty bucket and no variables. The previously recorded deployment is not changed or deleted. Use it when:

- the recorded deployment no longer exists, for example because it was deleted from the dashboard; `freepod deploy` reports this and suggests `init --force` or `link`;
- you want a second, independent deployment of the same source. Give it another `name` and `hostname`: both are refused while the old deployment holds them.

## Releasing

| Command | New build | Applies |
| --- | --- | --- |
| `freepod deploy` | Yes | Source, settings in `.freepod.json`, staged vars |
| `freepod apply` (or `freepod deploy --no-build`) | No | Settings in `.freepod.json`, staged vars |
| `freepod var set`, `freepod var rm` | No | The changed vars, staged vars |

Each of these creates one numbered release when it changes what runs: the image, a setting, or a var. A command that changes none of them creates no release, unless the deployment's last release failed, which it then retries. One release runs at a time per deployment: a command that starts a release while another is queued or running fails, and can be retried when the first one finishes. `freepod var set --stage` and `freepod var rm --stage` save changes without starting a release.

A release replaces the running container. The sequence is described under [Runtime contract: Releases](runtime.mdx#releases):

- The previous version serves traffic until the new container passes the [readiness check](runtime.mdx#readiness).
- Connections still open to the previous container, such as WebSockets or streaming responses, are closed when it stops.

## Failed releases

A release fails when the new container does not pass the readiness check within 5 minutes, for example because it exits at startup or does not listen on `$PORT`. The previous release keeps serving traffic.

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
| `failed` | Did not pass the readiness check in time; see [Failed releases](#failed-releases) |
| `abandoned` | Interrupted by a platform fault |

`--all` lists every release; `--verbose` prints full image references.

## Rolling back

There is no rollback command. Check out the previous version of the source and run `freepod deploy`.

## Stopping and starting

```bash
freepod stop
freepod start
```

`freepod stop` takes the project's deployment offline without deleting anything: nothing runs, its data, database, bucket and variables are kept, and its address answers with a "stopped" page and HTTP status `503`. It asks for no confirmation, because `freepod start` undoes it. Both commands wait until the change has been applied; `--no-wait` returns once Freepod has accepted it.

A stopped deployment runs again only when you start it. `freepod deploy` to a stopped deployment releases the new version but leaves it stopped, so the new version first runs at the next `freepod start`.

Only a deployment that is ready can be stopped or started. If its last release failed, a successful `freepod deploy` is needed first.

A deployment can be renamed, and given a description and an icon, under **Settings** on the [dashboard](app:/), or with `name`, `description` and `icon` in `.freepod.json` and `freepod apply`. This creates no release. The name is shown on the dashboard and on the deployment's **Sign in with Freepod** pages.

A deployment can also be stopped and started from the [dashboard](app:/).

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

`.freepod.json` keeps its settings and no longer records a deployment. `freepod init` in the project creates a new, empty deployment with them.

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
