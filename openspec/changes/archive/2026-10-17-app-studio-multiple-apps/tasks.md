# Tasks

## 1. Image: apps directory and creation (D1, D2, D3, D6)

- [x] 1.1 Add `image/bin/appstudio-new-app <name>`: check the D6 name rule and that `$APPSTUDIO_APPS_DIR/<name>` does not exist (message and non-zero exit otherwise), build the repository in `.new-<name>` (`git init -b main`, empty commit `Start <name>`), rename it into place, removing a leftover `.new-<name>` first. Copy it in the Dockerfile. Verify in the built image: `abc` and `recipes` create repos with one commit; `app` twice, `ab`, `My App`, `Recipes` (the script takes lowercase only), `-ab` and `ab-` are refused; two apps created in the same second have different root commits.
- [x] 1.2 Rework `image/bin/appstudio-start`: `APPSTUDIO_APPS_DIR` (default `/workspace/apps`) replaces `APPSTUDIO_PROJECT_DIR`; move `/workspace/app` to `<apps>/app` once and run `git worktree repair` there; create the first app with `appstudio-new-app app` when missing; run `opencode web` from `<apps>/app`. Verify in the built image against a volume holding a `/workspace/app` repo with a worktree under `/workspace/trees`: files, history and the worktree link survive; a second start changes nothing; with both folders present neither is touched; a fresh volume gets `apps/app`.

## 2. Image: dev tools (D7)

- [x] 2.1 Add `psmisc` to the Dockerfile's apt packages. Verify `fuser` runs in the built image.
- [x] 2.2 Make `dev-postgres` and `dev-s3` resolve the app from `git rev-parse --path-format=absolute --git-common-dir` in the current directory (`app` outside any app): database and bucket named after the app (`createdb -O app <name>`; a missing bucket created with `garage bucket create` plus `garage bucket allow --read --write --owner <bucket> --key <default key>`). Verify: exports from `apps/app` are unchanged from today; from `apps/recipes` and from a worktree of it they name database and bucket `recipes`; `psql` and an S3 put/get work against each.
- [x] 2.3 Make `dev-app` start the app of the current directory (refuse outside an app), stop its previous process group, then `fuser -k 8080/tcp`, then start. Verify: `dev-app` in `apps/app` then in `apps/recipes` leaves only `recipes` answering on 8080 with the `recipes` database; a hand-started `python -m http.server 8080` is stopped by `dev-app`.
- [x] 2.4 Update `products/appstudio/README.md` (apps directory, first app, `appstudio-new-app`, per-app dev database and bucket, one preview). Verify its spec links resolve.

## 3. Image: agent instructions (D9)

- [x] 3.1 Rewrite `image/AGENTS.md`: the app is the repository of the session's working directory; other folders under `/workspace/apps` are the owner's other apps and stay untouched unless asked; a new app means the New project button at the top and a new session there; drop the fixed path from the starter, publishing and secrets commands. Verify `grep -n /workspace/app AGENTS.md` finds only `/workspace/apps`, and in a studio session in a second app: the agent copies the starter into that app, and when asked for another app it points to New project without creating anything.
- [x] 3.2 Bump `image/VERSION`, build and push the image (`--build-context freepod-cli=cli`). Verify the pushed tag pulls and is a new version (never re-pushed).

## 4. Chart: values, SFTP, env (D1, D8)

- [x] 4.1 Replace `projectDir` with `appsDir` in `values.yaml`, `_helpers.tpl` (subPath check stays inside `/workspace`), the statefulset env (`APPSTUDIO_APPS_DIR`), the SFTP mount (subPath of `appsDir` at `/apps`, session root `volume:/apps`) and the chrome config (`apps`, `firstApp`); point `image` at the new version and bump the chart. Verify with `helm lint` and `helm template`.
- [x] 4.2 Update `api/tests/test_appstudio_chart.py`: the SFTP mount is the apps subPath read-only, the chrome config carries the apps directory and first app, `appsDir` outside `/workspace` is refused. Verify with `uv run pytest tests/test_appstudio_chart.py` in `api/`.

## 5. Chrome: project list sync and New project (D4, D5, D6)

- [x] 5.1 In `files/index.html`, load opencode through the D4 sequence: list the apps directory, add missing non-dot directories to `projects.local`, drop `/workspace/app`, then load the restored path, `/?home`, or on a first visit (empty project list) the example-prompt draft in the first app. Verify in a browser against the running studio (or the local harness with opencode 1.19.0): a fresh browser gets the example prompt in `app` and Home lists every app; a reload restores the open session without a prompt; an app made with `mkdir`+`git init` in a terminal appears after a reload; a stale `/workspace/app` entry disappears; with the listing failing opencode still loads.
- [x] 5.2 Add the New project button and form to the bar (D5, D6): validate the name and check it is not taken, `POST /pty` running `appstudio-new-app` scoped to the first app, poll the listing for up to 10 s, then blank the iframe, sync with `home.selection.directory` set, and load `/?home`; show validation, taken and timeout errors in the form. Match the bar's look in light and dark. Verify in a browser: from Home and from an open session, a new app opens on Home selected with no session and no prompt; `Recipes` creates `recipes`; `app`, `ab` and `My App` are refused without a request; the old session is still in the tab bar.
- [x] 5.3 Update the README's chrome row and `ui/docs/apps/products/appstudio.mdx` for New project and switching apps on opencode's Home. Verify the docs site builds (`npm run build` in `ui/docs`) and links resolve.

## 6. Release and rollout

- [x] 6.1 Point the catalog entry (`products/catalog/appstudio/appstudio.yaml`) at the new chart version, since `catalog apply` re-asserts it on every API rollout for both environments. Verify with `caelus catalog lint --dir ../products/catalog`.
- [x] 6.2 Publish the chart (`./scripts/publish-charts.sh appstudio`); move the dev studio to it ahead of the catalog rollout (a break-glass template, which the next dev API rollout replaces with the catalog's). Verify on `studio.erik.dev.freepod.eu`: `/workspace/apps/app` holds the old app and its git history; New project works; SFTP lists the app folders read-only; the preview follows `dev-app` between two apps.
- [x] 6.3 Prod follows the catalog when this change is merged and rolled out (product 16, Erik's studio). Verify the owner reaches the studio and the old app is in `apps/app`.

## Workflow follow-up

- Archive the change and sync `app-studio-projects` and `app-studio-access` into the main specs.
