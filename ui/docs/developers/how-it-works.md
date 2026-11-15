---
title: How it works
---

# How it works

The `freepod` client works with four objects: projects, deployments, builds and releases.

```
project directory ──freepod deploy──▶ build ──▶ release ──▶ deployment (https://<hostname>)
   .freepod.json                      image      rollout     runs the image, owns the
                                                             database, bucket and vars
```

## Project

A directory with a `.freepod.json` file, created by `freepod init`. Commands run from the project directory or any directory below it.

`.freepod.json` records which deployment the project belongs to, and any settings you choose to keep in it:

```json title=".freepod.json"
{
  "$schema": "https://freepod.eu/api/products/custom/project-schema",
  "version": 2,
  "deployment": "4de58a32-09c7-443f-8b86-694cfc818494",
  "name": "My app",
  "auth": { "enabled": true }
}
```

| Field | Contents |
| --- | --- |
| `$schema` | The file's JSON Schema, so editors can complete and check it |
| `version` | File format version |
| `deployment` | The deployment this project updates, written by `freepod init` or `freepod link` |
| `name`, `description`, `icon` | The app's name, description, and icon: a path to a PNG, JPEG or WebP image of at most 256 KiB |
| `hostname`, `auth`, … | The app's settings, such as [`auth`](authentication.mdx) |

Every key other than `$schema`, `version`, `env` and `deployment` is optional. Run `freepod apply` to send the file's settings without building; `freepod deploy` sends them with the build. Settings in the file are managed by it: the dashboard shows them read-only until you take one over there. Keys you leave out keep the value the app has.

Commit the file. Every checkout of the project, on any machine and in CI, then deploys to the same deployment. Older `.freepod.json` files are rewritten to this format the first time a command reads them.

## Deployment

A running application on Freepod. A deployment has:

- one hostname, served over HTTPS;
- one container running the deployment's current image;
- a [PostgreSQL database](storage/postgresql.mdx) and an [object storage bucket](storage/object-storage.mdx);
- [variables](variables-and-secrets.md) set with `freepod var`.

`freepod init` creates the deployment. Until its first build is released, it serves a placeholder page.

Deployments are also listed on the [dashboard](app:/), where they appear as apps.

## Build

A container image built from an upload of the project directory. `freepod deploy` uploads and builds; `freepod builds` lists a project's builds and `freepod builds log` prints a build's log. A build belongs to one deployment. See [Builds](builds/index.md).

## Release

One numbered rollout of a deployment. Each of these creates a release:

- `freepod deploy`, with a new build;
- `freepod apply`, when the file changes a setting the running app uses, or vars are staged;
- `freepod var set` and `freepod var rm`, without `--stage`.

`freepod releases` lists a deployment's releases and marks the one that is running. See [Deployments and releases](deployments-and-releases.md).
