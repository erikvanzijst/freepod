## Purpose

How one App Studio holds several apps: where they live, how the owner creates one from the studio's bar, how opencode's project list stays complete, what the first visit opens, and which app the agent and the live preview work on.

## ADDED Requirements

### Requirement: Each app is its own repository under the apps directory

Every app in a studio SHALL be a git repository directly under `/workspace/apps`, named by its folder, with a root commit no other app shares, so opencode treats each app as a separate project with its own sessions.

#### Scenario: Two apps are two projects

- **WHEN** the owner has apps `app` and `recipes`
- **THEN** opencode lists them as two projects, and a session started in one is not listed under the other

### Requirement: Every studio has a first app

A studio SHALL always have the app `/workspace/apps/app`. A studio that has none on start SHALL get it as an empty repository with one commit.

#### Scenario: New studio

- **WHEN** a studio starts for the first time
- **THEN** `/workspace/apps/app` exists as a git repository on `main` with one commit

### Requirement: The single-app layout moves once

On start, a studio that has `/workspace/app` and no `/workspace/apps/app` SHALL move `/workspace/app` to `/workspace/apps/app`, keeping its files and git history. It SHALL NOT overwrite an existing `/workspace/apps/app`.

#### Scenario: Existing studio upgraded

- **WHEN** a studio holding an app in `/workspace/app` restarts on this release
- **THEN** that app's files and commits are in `/workspace/apps/app` and `/workspace/app` is gone

#### Scenario: Both exist

- **WHEN** both `/workspace/app` and `/workspace/apps/app` exist on start
- **THEN** neither is changed and the studio starts

### Requirement: New project from the studio's bar

The studio's bar SHALL offer a New project action that asks for a name and creates that app under `/workspace/apps`. It SHALL NOT offer a list of apps; switching between apps is opencode's own.

#### Scenario: Creating an app

- **WHEN** the owner chooses New project and enters `recipes`
- **THEN** `/workspace/apps/recipes` is created as a git repository on `main` with one commit

### Requirement: Project names are checked before creation

The studio SHALL lowercase the name the owner types before using it. The result SHALL be 3 to 40 characters of letters, digits and hyphens, neither starting nor ending with a hyphen. A name that is invalid or already taken SHALL be refused with a message, and nothing SHALL be created.

#### Scenario: Name taken

- **WHEN** the owner enters `app`
- **THEN** the studio says the name is taken and creates nothing

#### Scenario: Uppercase is accepted

- **WHEN** the owner enters `Recipes`
- **THEN** the app `recipes` is created

#### Scenario: Too short

- **WHEN** the owner enters `ab`
- **THEN** the studio says how long a name must be and creates nothing

#### Scenario: Invalid name

- **WHEN** the owner enters `My App`
- **THEN** the studio says which characters a name may have and creates nothing

### Requirement: A new project opens on opencode's Home

After creating an app, the studio SHALL reload opencode on its Home screen with the new app in its project list and selected, whatever opencode was showing before. It SHALL NOT open a session or type a prompt.

#### Scenario: Created from an open session

- **WHEN** the owner creates `recipes` while a session in `app` is open
- **THEN** opencode shows its Home with `recipes` selected and no sessions in it, and the session in `app` stays available

### Requirement: A half-created app is never listed

An app SHALL appear under its name in `/workspace/apps` only once its repository and first commit exist, so that nothing registers it in an unfinished state.

#### Scenario: Creation in progress

- **WHEN** the studio lists `/workspace/apps` while `recipes` is being created
- **THEN** `recipes` is either absent or a repository with its first commit

### Requirement: opencode's project list includes every app

Each time the studio page loads, before opencode starts in it, the studio SHALL add every app under `/workspace/apps` that the browser's opencode project list lacks, and SHALL remove the entry for `/workspace/app`. Folders whose names start with a dot SHALL NOT be added. Projects the owner opened elsewhere SHALL be kept.

#### Scenario: New browser

- **WHEN** the owner opens the studio in a browser that has never loaded it, and the studio has apps `app` and `recipes`
- **THEN** opencode's Home lists both

#### Scenario: App created outside the bar

- **WHEN** an app folder was created from a terminal and the owner reloads the studio
- **THEN** opencode's Home lists it

#### Scenario: Listing fails

- **WHEN** the studio cannot list `/workspace/apps`
- **THEN** opencode still loads, with the project list the browser already had

### Requirement: The first visit opens the first app with the example prompt

When a browser has no opencode projects before the studio adds them, the studio SHALL open a new session in the first app with the example prompt typed in and not sent. Any later load SHALL return to where opencode was, or its Home.

#### Scenario: First visit

- **WHEN** the owner opens the studio for the first time in a browser
- **THEN** a new session in `app` is open with the example prompt in the input box

#### Scenario: Later visits

- **WHEN** the owner opens the studio again in that browser
- **THEN** no new session is opened and no prompt is typed in

### Requirement: The agent works on its session's app

The agent's instructions SHALL identify the app as the git repository of the session's working directory, keep the agent out of the other apps unless the owner asks, and have it point an owner who asks for a new app within a session to the New project button.

#### Scenario: Request for a second app

- **WHEN** the owner asks, in a session in `app`, to start a different app
- **THEN** the agent tells them to use New project and start a session there, and creates nothing in `app` for it

### Requirement: One app in the preview at a time

The preview SHALL show the app most recently started with the studio's dev-server command, run from that app's directory or one of its worktrees. Starting it SHALL first stop whatever listens on the preview port, whichever app or process it is.

#### Scenario: Switching the previewed app

- **WHEN** `app` runs in the preview and the agent starts `recipes`
- **THEN** `app` stops and the preview shows `recipes`

#### Scenario: Port held by another process

- **WHEN** a process not started by the dev-server command listens on the preview port
- **THEN** starting an app stops it and the app takes the port

### Requirement: Each app has its own local database and bucket

The local PostgreSQL database and S3 bucket given to an app in the studio SHALL be named after its folder, so apps never share tables, migrations or objects. The first app keeps the name `app`.

#### Scenario: Two apps with migrations

- **WHEN** `app` and `recipes` each run their migrations locally
- **THEN** each has its own tables in its own database

#### Scenario: Worktree of an app

- **WHEN** the dev server runs from an opencode worktree of `recipes`
- **THEN** it uses the `recipes` database and bucket
