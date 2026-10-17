# Proposal

## Why

An App Studio holds exactly one app: `/workspace/app` is fixed in the agent's
instructions, the dev tools, the SFTP mount and the page around opencode. A user
who wants a second app needs a second studio deployment, with its own workspace,
sign-in and Freepod login. opencode already treats every git repository as a
separate project with its own sessions, but its web UI cannot create a folder,
its folder picker starts in the container's home directory, and the agent's
instructions push every request back into `/workspace/app`.

## What Changes

- **Apps live in `/workspace/apps/<name>`**, one git repository each, so
  opencode keeps each app's sessions apart. Every studio has a first app,
  `/workspace/apps/app`. **BREAKING** for existing studios: `/workspace/app` is
  moved there once on start; sessions opencode recorded under the old path stay
  behind.
- **A "New project" button in the studio's bar.** It asks for a name, creates
  the app's repository through opencode's own terminal API, and reloads opencode
  on its Home screen with the new project selected. There is no app list in the
  bar; switching between apps is opencode's own Home.
- **opencode always knows every app.** Each time the studio page loads, it adds
  every app under `/workspace/apps` that the browser's opencode project list
  lacks, before opencode starts, and drops the old `/workspace/app` entry.
- **The first visit is unchanged**: a fresh session in the first app with the
  example prompt typed in. A new project never gets the example prompt.
- **The agent works on the session's app.** Its instructions name the session's
  working directory instead of `/workspace/app`, keep it out of the other apps,
  and send a user who asks for a new app inside a session to the New project
  button.
- **One preview at a time.** `dev-app` runs the app of the directory it is
  called from and stops whatever else holds the preview port first. Each app
  gets its own local database and S3 bucket, named after its folder.
- **SFTP reaches every app.** The read-only SFTP session's root becomes
  `/workspace/apps` instead of the single project directory; credentials stay
  out of reach.
- Out of scope: deleting or renaming apps, previewing several apps at once.

## Capabilities

### New Capabilities
- `app-studio-projects`: how an App Studio holds several apps — where they
  live, the first app, creating one from the studio's bar, keeping opencode's
  project list complete, the first visit, which app the agent and the preview
  work on.

### Modified Capabilities
- `app-studio-access`: SFTP exposes the apps directory, every app in it, rather
  than one project directory.

## Impact

- `products/appstudio/image/`: new `appstudio-new-app`; `appstudio-start`
  (apps directory, first app, one-time move); `dev-app`, `dev-postgres`,
  `dev-s3` (app from the working directory, per-app database and bucket,
  freeing the preview port); `AGENTS.md`; a new image version.
- `products/appstudio/chart/`: `projectDir` gives way to the apps directory;
  the chrome page (`files/index.html`) gains the New project button and the
  project-list sync; the SFTP mount; tests in `api/tests/test_appstudio_chart.py`;
  a new chart version.
- `products/appstudio/README.md` and the product's docs page.
- New App Studio template versions on dev and prod, and the existing studios
  moved to them.
- Coupling: the chrome relies on opencode 1.19's file-listing and terminal
  APIs and its browser storage shapes, as it already does for the first visit.
