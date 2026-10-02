# Builds

`freepod deploy` uploads the project directory and builds a container image from it on Freepod. No local Docker installation is needed.

## Builders

| Project root contains | Builder |
| --- | --- |
| `Dockerfile` | The Dockerfile is built. |
| No `Dockerfile` | [Railpack](https://railpack.com) detects the language and framework and builds an image. |

The first line of the build log names the builder. To build a project that has a `Dockerfile` with Railpack instead, rename the file or exclude it in `.freepodignore`.

## Railpack

Railpack detects the language from the project's files, installs dependencies, runs the build step and sets a start command. See the [Railpack documentation](https://railpack.com) for supported languages and their configuration.

Language guides:

- [Node.js](nodejs.md)
- [Python](python.md)
- [Go](go.md)

### Start command

Railpack infers the start command. To set it explicitly, add a [`Procfile`](https://railpack.com/config/procfile) to the project root with a `web` entry:

```procfile title="Procfile"
web: node server.js
```

The command must start a server on `0.0.0.0:$PORT`. See [Runtime contract](../runtime.mdx).

### Build-time variables

Variables set with `freepod var` are available to the running container only, not during the build. A build that reads environment variables gets them from one of these:

- **[`railpack.json`](https://railpack.com/config/file)** in the project root. Variables declared under a step are set in that step's environment:

  ```json title="railpack.json"
  {
    "$schema": "https://schema.railpack.com",
    "steps": { "build": { "variables": { "SIMPLE_MODE": "true" } } }
  }
  ```

  A top-level `variables` or `env` object has no effect.

- **Dotenv files** read by the project's own tooling, such as `.env.production` for Vite or Next.js. They are uploaded with the project unless `.gitignore` excludes them. `.env.local` and `.env.*.local` are never uploaded.

Both are committed to the repository and end up in the image. There is no mechanism for build-time secrets.

## Dockerfile

When the project root contains a `Dockerfile`:

- `Procfile` and `railpack.json` are ignored.
- The image must still serve HTTP on `0.0.0.0:$PORT`. The build log warns if the image's `EXPOSE` ports do not include the platform's port.
- The Dockerfile frontend is fixed by the platform. A `# syntax=` directive has no effect.
- `RUN --security=insecure` and `RUN --network=host` are not available.
- Base images are pulled from the registry the Dockerfile names. Anonymous pulls from Docker Hub are subject to its rate limits.
- Build arguments use the `ARG` defaults in the Dockerfile; `freepod deploy` does not pass build arguments.

## What is uploaded

The project directory, minus:

1. `.git/`, always;
2. files matched by `.gitignore` files, unless `freepod deploy --no-gitignore` is used;
3. these defaults: `node_modules/`, `.venv/`, `venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `target/`, `dist/`, `build/`, `.DS_Store`, `*.swp`, `.env.local`, `.env.*.local`;
4. files matched by `.freepodignore` in the project root.

`.freepodignore` uses `.gitignore` syntax and is applied last, so a `!` pattern in it can re-include a file excluded by the earlier rules. The negation must name the path, for example `!build/static/`, and a file inside a directory excluded with a trailing slash cannot be re-included; exclude `build/*` instead of `build/` to allow exceptions.

## Limits

| | Limit |
| --- | --- |
| Upload size, compressed | 100 MB |
| Build duration | 1 hour |
| Build resources | 2 vCPU, 6 GiB memory |
| Architecture | `linux/amd64` |

A build may wait in a queue before it starts. Image layers are cached per account, so later builds reuse unchanged layers.

## Listing builds

```bash
freepod builds          # latest 20
freepod builds --all
```

The build the deployment is running is marked with `*`.
