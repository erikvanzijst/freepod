## MODIFIED Requirements

### Requirement: opencode's project list includes every app

Each time the studio page loads, before opencode starts in it, the studio SHALL add every app under `/workspace/apps` that the browser's opencode project list lacks. Folders whose names start with a dot SHALL NOT be added. Projects the owner opened elsewhere SHALL be kept.

#### Scenario: New browser

- **WHEN** the owner opens the studio in a browser that has never loaded it, and the studio has apps `app` and `recipes`
- **THEN** opencode's Home lists both

#### Scenario: App created outside the bar

- **WHEN** an app folder was created from a terminal and the owner reloads the studio
- **THEN** opencode's Home lists it

#### Scenario: Listing fails

- **WHEN** the studio cannot list `/workspace/apps`
- **THEN** opencode still loads, with the project list the browser already had

## REMOVED Requirements

### Requirement: The single-app layout moves once

**Reason**: Every studio already uses the apps directory layout.

**Migration**: None.
