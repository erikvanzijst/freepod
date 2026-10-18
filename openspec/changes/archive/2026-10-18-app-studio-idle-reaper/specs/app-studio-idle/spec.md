# Spec Delta

## Purpose

How an App Studio releases the memory held by what the agent left running once nobody is using it, and brings the preview back when the owner returns.

## ADDED Requirements

### Requirement: A studio is idle after 30 minutes unused

A studio SHALL count as idle once, for 30 minutes, no browser has been connected to it and no agent session has been working or producing output. A connection from inside the studio's own container SHALL NOT count as a browser.

#### Scenario: Owner closes the tab

- **WHEN** the owner closes the studio's last tab and the agent is not working
- **THEN** the studio becomes idle 30 minutes later

#### Scenario: Agent still working

- **WHEN** the owner closes the tab while the agent is in the middle of a task
- **THEN** the studio does not become idle until 30 minutes after the agent finished

#### Scenario: Tab in the background

- **WHEN** the studio's tab stays open in the background with the agent not working
- **THEN** the studio does not become idle

#### Scenario: Terminal session inside the container

- **WHEN** the only client connected to opencode runs inside the studio's container
- **THEN** the studio becomes idle as if no client were connected

### Requirement: An idle studio stops what was left running

When a studio becomes idle it SHALL stop PostgreSQL, Garage and every process left running in the background after the command that started it ended, whichever app or command started it, and SHALL stop the agent's Playwright MCP servers and browsers. opencode, its sessions and its open terminals SHALL keep running.

#### Scenario: Preview and database running

- **WHEN** a studio with an app in the preview, PostgreSQL and Garage running becomes idle
- **THEN** the app, PostgreSQL and Garage are stopped, and the workspace, the app's database contents and its bucket's objects are kept

#### Scenario: App started without dev-app

- **WHEN** the agent started an app on another port with its own command, and the studio becomes idle
- **THEN** that app is stopped as well

#### Scenario: Process started in an open terminal

- **WHEN** a process started in a studio terminal is still attached to that open terminal
- **THEN** it keeps running when the studio becomes idle

#### Scenario: Sessions after idle

- **WHEN** the owner returns to a studio that was idle
- **THEN** every session is listed as before and the agent can use its tools, including the browser

### Requirement: The preview returns with the owner

When a browser connects to a studio that stopped what was left running, the studio SHALL start the app that was in the preview again, from the same directory and with its local database and bucket, without the owner or the agent asking. Apps that were running outside the preview SHALL NOT be started again.

#### Scenario: Owner reopens the studio

- **WHEN** the owner opens a studio that went idle with `recipes` in the preview
- **THEN** within seconds the Preview button lights up again and shows `recipes` with its data

#### Scenario: Nothing was in the preview

- **WHEN** the owner opens a studio that went idle with nothing in the preview
- **THEN** nothing is started

### Requirement: The agent's browser closes after 10 minutes unused

The agent's headless browser SHALL close after 10 minutes without a browser tool call, whether or not the studio is idle, and the next browser tool call SHALL open a new one.

#### Scenario: Agent stops browsing

- **WHEN** the agent's last browser tool call was 10 minutes ago
- **THEN** no headless browser process runs in the studio

#### Scenario: Agent browses again

- **WHEN** the agent makes a browser tool call after its browser closed
- **THEN** the call succeeds in a newly opened browser

### Requirement: The agent restarts what it needs

The agent's instructions SHALL tell it that the dev server, the database and S3 may have been stopped while the studio was idle, and to start them again with the studio's commands instead of assuming they run.

#### Scenario: Agent resumes after idle

- **WHEN** the owner returns after the studio was idle and asks the agent to run a migration
- **THEN** the agent starts the database with the studio's command before running it
