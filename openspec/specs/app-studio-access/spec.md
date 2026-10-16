# app-studio-access Specification

## Purpose

Who may reach an App Studio deployment: its studio hostname and the live preview of the app being built are both open to the deployment's owner only, through Sign in with Freepod.

## Requirements

### Requirement: The studio and its preview require the owner's sign-in

Every request to an App Studio deployment's hostname and to its preview hostname SHALL pass the platform's app authentication before reaching the studio or the preview, with authentication always enabled. The chart SHALL NOT offer a way to serve either hostname without it.

#### Scenario: Anonymous visitor

- **WHEN** a browser without a session opens the studio's hostname
- **THEN** it is sent to sign in with Freepod and reaches nothing of the studio first

#### Scenario: Preview needs the same sign-in

- **WHEN** a browser without a session opens the preview hostname
- **THEN** it is sent to sign in with Freepod before seeing the preview

### Requirement: Only the owner is allowed

The only account allowed to reach either hostname SHALL be the deployment's owner, identified by the owner's email address as the platform injects it. A different signed-in Freepod account SHALL be refused on both hostnames. The allowed account SHALL come only from platform-injected values, never from the deployment's user values.

#### Scenario: Owner signs in

- **WHEN** the deployment's owner signs in on the studio's hostname
- **THEN** the studio loads

#### Scenario: Another account signs in

- **WHEN** a Freepod account other than the owner signs in on the studio or preview hostname
- **THEN** it is refused and sees a page saying it has no access

#### Scenario: User values cannot widen access

- **WHEN** a deployment's user values try to add an allowed account
- **THEN** schema validation rejects them

### Requirement: No owner, no studio

When the platform has not injected the owner's email or the verifier's address, the chart SHALL fail to render rather than serve either hostname with weaker access control.

#### Scenario: Owner email missing

- **WHEN** an App Studio deployment is rendered without the owner's email
- **THEN** rendering fails and the previous release keeps serving

### Requirement: Identity headers stripped

Requests to both hostnames SHALL have client-supplied identity headers removed before the verifier sets its own, as for every other app with a hostname.

#### Scenario: Spoofed header

- **WHEN** a client sends `X-Freepod-Email: owner@example.com` to the preview hostname
- **THEN** the preview receives the verifier's identity headers only

### Requirement: Project files are readable over SFTP

The owner SHALL be able to copy files out of the project directory over the platform's SFTP access, with the same SSH keys and connection details as any other deployment. The session SHALL be read-only and SHALL expose the project directory alone: the rest of the workspace, which holds the owner's Freepod credentials and the studio's configuration, SHALL NOT be reachable through it.

#### Scenario: Getting a file out

- **WHEN** the owner connects over SFTP with a key registered on their account
- **THEN** they see the project directory and can download its files

#### Scenario: Credentials stay out of reach

- **WHEN** the owner lists everything the SFTP session can reach
- **THEN** the workspace's configuration directory is not among it

#### Scenario: Read-only

- **WHEN** the owner tries to upload or delete a file over SFTP
- **THEN** the write is refused

