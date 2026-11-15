# Spec Delta

## Purpose

`freepod apply`: the command that sends a project file's keys to its deployment without
building. Editing the file and applying it is how a developer changes the deployment
from the command line.

## ADDED Requirements

### Requirement: Apply sends the project file to its deployment

`freepod apply` SHALL send one update to the recorded deployment, built from every key of
the project file other than `$schema`, `version`, `env` and `deployment`. `name`,
`description` and `icon` SHALL be sent as the deployment's identity. Every other key
SHALL be sent as a chart value, replacing the deployment's stored value for that key
whole, with the stored values of the keys the file does not hold sent unchanged. Apply
SHALL NOT upload the project directory or build anything.

#### Scenario: Renaming through the file

- **WHEN** a developer sets `"name": "Arkanoid"` in `.freepod.json` and runs `freepod apply`
- **THEN** the deployment is named `Arkanoid`
- **AND** nothing is built

#### Scenario: Replacing a nested object

- **WHEN** a deployment has `auth` = `{"enabled": true, "access": "listed"}`, the file holds `"auth": {"enabled": true}`, and the developer applies
- **THEN** the deployment's `auth` is `{"enabled": true}`, and access falls back to the default

#### Scenario: An unlinked project

- **WHEN** `freepod apply` runs in a project whose file records no deployment
- **THEN** it fails and names `freepod init` and `freepod link`

### Requirement: Apply claims exactly the file's keys

The update apply sends SHALL carry `managed_fields` listing exactly the file's keys other
than `$schema`, `version`, `env` and `deployment`.

#### Scenario: Claiming the file's keys

- **WHEN** the file holds `name` and `auth` and the developer applies
- **THEN** the deployment's managed fields are `name` and `auth`

#### Scenario: A key removed from the file

- **WHEN** a developer removes `auth` from the file and applies
- **THEN** `auth` is no longer managed and keeps its value

### Requirement: The icon is sent with every apply

The file's `icon` SHALL be a path relative to the project root, and apply SHALL send the
file's contents as base64 with every update. A path that does not exist, or a file
larger than 256 KiB, SHALL fail the command before anything is sent. A null `icon` SHALL
clear the deployment's icon.

#### Scenario: A missing icon file

- **WHEN** `icon` names a file that does not exist
- **THEN** apply fails, naming the path, and nothing is sent

#### Scenario: An oversized icon

- **WHEN** `icon` names a 2 MiB PNG
- **THEN** apply fails, naming the 256 KiB limit, and nothing is sent

### Requirement: Apply reports what it changed

Apply SHALL compare the file with the deployment as it read it before the update, and
print each key whose value changed, showing the old and new values. For any value longer
than one line it SHALL say only that the key changed. The icon SHALL NOT be reported,
because reads carry no fingerprint of it to compare against. When nothing changed it
SHALL say so. When a release was created, it SHALL follow the rollout as deploy does.

#### Scenario: A rename

- **WHEN** apply changes the name from `arkanoid` to `Arkanoid`
- **THEN** it prints `name: "arkanoid" → "Arkanoid"`

#### Scenario: A field claimed back from the dashboard

- **WHEN** the owner changed a description in the dashboard after taking it over, and the file still holds the old one
- **THEN** apply restores the file's description and prints the change

#### Scenario: Nothing to do

- **WHEN** the file matches the deployment and no vars are pending
- **THEN** apply reports that nothing changed and creates no release

### Requirement: Apply rolls out staged vars

When the deployment's vars are pending, apply SHALL create a release from the current
image, as `freepod deploy --no-build` does, and `--no-build` SHALL be an alias of apply.

#### Scenario: Applying staged vars

- **WHEN** vars were staged with `freepod var set --stage` and the developer runs `freepod apply`
- **THEN** a release is created from the current image and the vars take effect

### Requirement: Other project commands warn about unapplied changes

Project commands other than `apply`, `deploy` and `init` SHALL print a one-line warning
when a key in the project file other than `icon` differs from the deployment, naming
`freepod apply`. The warning SHALL NOT change the command's outcome or exit status.

#### Scenario: Checking logs after editing the file

- **WHEN** the file's `description` differs from the deployment's and the developer runs `freepod log`
- **THEN** the logs are shown, with a warning that the project file has changes not yet applied
