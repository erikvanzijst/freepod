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

`.freepod.json` records the deployment's settings and, after the first deploy, which deployment the project belongs to:

```json title=".freepod.json"
{
  "version": 1,
  "deployment": {
    "id": "4de58a32-09c7-443f-8b86-694cfc818494",
    "name": "custom-user-app-l2dhi5"
  },
  "user_values": {
    "hostname": "myapp.alice.freepod.eu"
  }
}
```

| Field | Contents |
| --- | --- |
| `version` | File format version |
| `deployment` | The deployment this project updates. Written by the first `freepod deploy`. |
| `user_values` | Deployment settings: `hostname`, and optionally `auth` (see [Authentication](authentication.mdx)). Edit them and run `freepod deploy` to apply them. |

Commit the file. Every checkout of the project, on any machine and in CI, then deploys to the same deployment.

## Deployment

A running application on Freepod. A deployment has:

- one hostname, served over HTTPS;
- one container running the deployment's current image;
- a [PostgreSQL database](storage/postgresql.mdx) and an [object storage bucket](storage/object-storage.mdx);
- [variables](variables-and-secrets.md) set with `freepod var`.

The first `freepod deploy` of a project creates the deployment. Until its first build is released, it serves a placeholder page.

Deployments are also listed on the [dashboard](app:/), where they appear as apps.

## Build

A container image built from an upload of the project directory. `freepod deploy` uploads and builds; `freepod builds` lists a project's builds. A build belongs to one deployment. See [Builds](builds/index.md).

## Release

One numbered rollout of a deployment. Each of these creates a release:

- `freepod deploy`, with a new build;
- `freepod deploy --no-build`, with the current image;
- `freepod var set` and `freepod var rm`, without `--stage`.

`freepod releases` lists a deployment's releases and marks the one that is running. See [Deployments and releases](deployments-and-releases.md).
