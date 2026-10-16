# Spec Delta

## Purpose

Who may reach an App Studio deployment: its studio hostname and the live
preview of the app being built are both open to the deployment's owner only,
through Sign in with Freepod.

## ADDED Requirements

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
