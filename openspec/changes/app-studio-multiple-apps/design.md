# Design

## Context

The studio pod runs `opencode web` (1.19.0) from one project directory, with a
`chrome` nginx sidecar serving the page around it (`/.appstudio/`) on the same
origin. That page already writes opencode's browser storage on a first visit
(the project list in `opencode.global.dat:server`, a draft tab in
`opencode.window.browser.dat:tabs`) before loading opencode in an iframe.

Established with opencode 1.19.0 in a browser, behind a same-origin page like
the chrome (harness in `var/appstudio/switch-test/`):

- opencode reads its project list from localStorage at startup only, with no
  cross-document sync. A write made while it runs is invisible to it and is
  overwritten at its next save of that key.
- Opening `/<base64 dir>/session` does not add the project to the list, and the
  `opencode:deep-link` "open project" event is ignored unless the server is on
  `localhost`.
- Once a project is in the list, opencode's Home shows it under Projects;
  selecting one filters the sessions and offers New session. Home's selection
  is persisted in `opencode.global.dat:layout` → `home.selection.directory`,
  and setting it before load opens Home on that project.
- `GET /file?directory=<dir>&path=.` lists a directory's entries
  (`name`, `type`, `absolute`).
- `POST /pty` with `{command, args, cwd}` runs a command with no terminal
  attached; opencode removes the PTY when the command exits, so its exit status
  and output are not retrievable afterwards.
- The web UI's folder picker can only open existing folders and starts at
  `$HOME` (`/root`); upstream `dev` adds no folder creation.

## Goals / Non-Goals

**Goals:**
- No new server process: the chrome stays static nginx and talks to opencode's
  own API.
- Reuse opencode's Home as the app switcher, so there is no second list to keep
  in step with opencode's project names.

**Non-Goals:**
- Changing opencode's folder picker or hiding its "add project" button.
- Separating apps in opencode's tab bar; tabs of different apps sit side by
  side, as opencode designs it.
- Keeping the chat history of the moved first app reachable from its new path.

## Decisions

### D1. Apps directory and the first app

`/workspace/apps/<name>`, first app `app`. The chart's `projectDir` value is
replaced by `appsDir` (default `/workspace/apps`, still checked to lie inside
`/workspace`); the first app is always `<appsDir>/app`. The container gets
`APPSTUDIO_APPS_DIR`; `APPSTUDIO_PROJECT_DIR` goes. `opencode web` keeps running
from the first app, so requests without a directory resolve to a real project.
*Alternative:* apps directly under `/workspace`. Rejected: `/workspace` also
holds `.config` (the owner's Freepod credentials) and `trees`, which SFTP must
not reach and the project sync must not list.

### D2. One creation script, atomic by rename

`appstudio-new-app <name>` validates the name (D6), refuses an existing folder,
builds the repository in `<appsDir>/.new-<name>` (`git init -b main`, an empty
commit `Start <name>`), then renames it to `<appsDir>/<name>`. The rename is the
last step, so an app's name appears in a listing only when complete, and the
commit message makes each root commit (opencode's project id) distinct even for
apps created in the same second. `appstudio-start` uses the same script for the
first app.

### D3. One-time move in `appstudio-start`

If `/workspace/app` exists and `<appsDir>/app` does not, `mv` it, then run
`git worktree repair` from the moved repository so the worktrees opencode made
under `/workspace/trees` point at the new location. Nothing else is touched;
both existing is logged and left alone. opencode identifies the moved project
by the same root commit, but its sessions recorded the old directory, so old
chats may not reopen; accepted for the two existing studios.

### D4. The chrome loads opencode in three steps

Every load of the chrome page, and every New project:

1. iframe → `about:blank` (only when opencode is loaded), so opencode cannot
   overwrite what follows;
2. list `<appsDir>` (`GET /file?directory=<appsDir>&path=.`), add each
   directory not starting with `.` that is missing from `projects.local`, and
   drop `/workspace/app`; on New project also set `home.selection.directory`;
3. load the destination: the fragment-restored path, or `/?home`, or on a first
   visit the draft session with the example prompt (as today, in the first app).

A first visit is a browser whose `projects.local` is empty before step 2. If the
listing fails, step 3 runs with the list as it was.
*Alternative:* write storage while opencode runs and navigate inside the
iframe. Rejected: the write is overwritten (verified).
*Alternative:* open a session in the new app instead of Home. Rejected by
choice: a fresh session in another project looks identical to the one the user
left, and opencode shows no project in a session view.

### D5. New project goes through opencode's terminal API

The button opens a small form in the bar. On submit the chrome checks the name
(D6) and the listing (taken?), then `POST /pty?directory=<first app>` with
`{command: "appstudio-new-app", args: [name], cwd: <appsDir>}`, then polls the
listing every 300 ms for up to 10 s for `name`, and runs D4 with it selected.
No appearance in time shows an error in the form. The PTY is scoped to the first
app rather than `<appsDir>`, because a request scoped to a non-git directory
makes opencode instantiate it as a project of its own.
*Alternative:* a small HTTP endpoint in the opencode container or a dynamic
sidecar. Rejected: a new process and attack surface for one `mkdir`, while the
PTY API already grants the owner a shell (`/terminal`).

### D6. Name rule

The page lowercases what the owner types before checking or sending it, so
`Recipes` needs no error. The rule, checked in the page and again in the script:
`^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$`: 3–40 characters, a safe folder and
command argument (no leading hyphen), a valid PostgreSQL database name, and a
valid S3 bucket name (3–63 characters), so the bucket needs no other name.
Other characters (spaces, dots, slashes) are refused, not rewritten.

### D7. Dev tools resolve the app from git

`dev-app`, `dev-postgres` and `dev-s3` find the app as the folder holding
`git rev-parse --path-format=absolute --git-common-dir`, so a worktree under
`/workspace/trees` resolves to its app. The database and bucket are named after
it; `app` keeps today's names, so the first app's local data is unaffected.
`dev-postgres` creates the database owned by the shared `app` role; `dev-s3`
creates a missing bucket with `garage bucket create` and grants the default key
read, write and owner on it.

`dev-app` stops its own previous process group, then frees port 8080 with
`fuser -k 8080/tcp` (`psmisc` is added to the image; it has no `fuser`, `ss` or
`lsof` today), then starts the app of the current directory. The log and pid
files stay global: there is one preview.

### D8. SFTP root

The SSH sidecar mounts the `apps` subPath of the workspace volume read-only at
`/apps`, session root `volume:/apps`. Users see one folder per app.

### D9. Agent instructions

`AGENTS.md` replaces `/workspace/app` with "your working directory" (opencode
gives the agent its working directory), says that sibling folders under
`/workspace/apps` are the owner's other apps and are off limits unless asked,
and tells the agent that a new app needs the New project button and a new
session, since a session cannot change its directory. Commands in it (`cd
/workspace/app && freepod …`) drop the fixed path.

## Risks / Trade-offs

- [The chrome depends on opencode 1.19's storage shapes and API paths] → the
  chrome already does for the first visit; opencode is pinned, and an upgrade
  re-runs the browser checks in the harness before release.
- [`POST /pty` failure output is invisible] → names are validated before the
  call and the script has a single failure mode the page also checks (taken);
  a timeout tells the owner to retry.
- [Reload on New project discards in-memory UI state, such as an unsent prompt
  in the open session] → the owner chose to leave the session; accepted.
- [`fuser -k` kills any listener on 8080, including one the owner started by
  hand] → that is the requirement: one preview, whoever holds it.
- [Old sessions of the moved first app may not reopen] → accepted; two studios
  exist, both the author's.

## Migration Plan

1. Release the image and chart, and point the catalog entry at the chart: App
   Studio is curated, so `catalog apply` on each API rollout creates the template
   version on dev and prod. The dev studio is tried first on a break-glass
   template, which the next dev rollout replaces with the catalog's.
2. On restart each studio moves `/workspace/app` (D3); the next page load
   replaces the old project entry in the browser (D4).
3. Rollback: the previous template version expects `/workspace/app`; move
   `/workspace/apps/app` back by hand before downgrading.
