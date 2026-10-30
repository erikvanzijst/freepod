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

### Requirement: Identity headers stripped

Requests to both hostnames SHALL have client-supplied identity headers removed before the verifier sets its own, as for every other app with a hostname.

#### Scenario: Spoofed header

- **WHEN** a client sends `X-Freepod-Email: owner@example.com` to the preview hostname
- **THEN** the preview receives the verifier's identity headers only

### Requirement: Project files are readable over SFTP

The owner SHALL be able to copy files out of every app in the studio over the platform's SFTP access, with the same SSH keys and connection details as any other deployment. The session SHALL be read-only and SHALL expose the apps directory alone, each app as a folder in it: the rest of the workspace, which holds the owner's Freepod credentials and the studio's configuration, SHALL NOT be reachable through it.

#### Scenario: Getting a file out

- **WHEN** the owner connects over SFTP with a key registered on their account
- **THEN** they see a folder per app and can download its files

#### Scenario: Credentials stay out of reach

- **WHEN** the owner lists everything the SFTP session can reach
- **THEN** the workspace's configuration directory is not among it

#### Scenario: Read-only

- **WHEN** the owner tries to upload or delete a file over SFTP
- **THEN** the write is refused

### Requirement: Only the studio's own origin may frame it
The studio's Ingress SHALL answer every response with
`X-Frame-Options: SAMEORIGIN`, through a Middleware of the chart's own, so the
chrome can frame opencode from the studio's origin and no other origin can
frame either. The preview's Ingress SHALL NOT carry it.

#### Scenario: The studio Ingress refuses other origins' frames
- **WHEN** the chart is rendered with an ingress host
- **THEN** `<release>-ingress` lists `<release>-frame-self`, which sets `X-Frame-Options: SAMEORIGIN`
- **AND** `<release>-preview` does not list it

### Requirement: The owner and the people they list are allowed

An App Studio template SHALL set `auth.enabled: true` and `auth.access: listed` as system values and offer neither in its user values. Only the deployment's owner and the people on its access list SHALL reach the studio or its preview. With an empty list, which is how every studio starts, only the owner SHALL reach either hostname.

#### Scenario: Owner signs in

- **WHEN** the deployment's owner signs in on the studio's hostname
- **THEN** the studio loads

#### Scenario: Another account signs in

- **WHEN** a Freepod account that is neither the owner nor listed signs in on the studio or preview hostname
- **THEN** it is refused and sees a page saying it has no access

#### Scenario: The owner lists someone

- **WHEN** the owner adds Sam to the studio's access list and Sam signs in on the studio's hostname
- **THEN** the studio loads for Sam

#### Scenario: User values cannot widen access

- **WHEN** a deployment's user values try to set `auth.access: anyone`
- **THEN** schema validation rejects them

### Requirement: No verifier, no studio

The chart SHALL fail to render when the platform has not injected the verifier's address, or when its values do not set `auth.enabled: true`, `auth.protocol: header` and `auth.access: listed`, rather than serve either hostname with weaker access control.

#### Scenario: Verifier address missing

- **WHEN** an App Studio deployment is rendered without the verifier's address
- **THEN** rendering fails and the previous release keeps serving

#### Scenario: Open access

- **WHEN** an App Studio deployment is rendered with `auth.access: anyone`
- **THEN** rendering fails
