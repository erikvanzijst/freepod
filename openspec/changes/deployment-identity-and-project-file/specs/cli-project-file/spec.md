# Spec Delta

## MODIFIED Requirements

### Requirement: A project is described by a committed JSON file

The client SHALL record a project in a file named `.freepod.json` at the project root, in
JSON. The file SHALL carry `version` 2 and `$schema`, and, once linked, the deployment
pointer. It SHALL name the environment it belongs to only when that is not the default
(`prod`). A file that names none belongs to the default environment, and a file that
names `prod` explicitly SHALL keep working and keep that entry. Every other key is a
deployment field the file manages (deployment-project-file).

The file SHALL contain no credentials or other secrets, so that committing it to version
control is safe and expected.

#### Scenario: The file describes a project before its first deploy

- **WHEN** a project has been initialized on the default environment
- **THEN** `.freepod.json` holds `$schema`, `version` and `deployment`, and nothing else

#### Scenario: The file is safe to commit

- **WHEN** `.freepod.json` is inspected
- **THEN** it contains no token, key, or other credential material

### Requirement: The recorded environment selects the target

The environment the project file records — the default one when it names none — SHALL
be the environment every command run from the project targets unless one is selected
explicitly.

A command that targets another environment SHALL NOT be refused for disagreeing with the
file. It SHALL be refused only where the recorded deployment would be stranded by
proceeding, and by the command that knows what that deployment is for, because a
deployment identifier has no meaning in another environment.

The recorded environment SHALL be written together with the deployment it describes, so
that the file never names an identifier the environment it declares cannot answer for.

#### Scenario: The recorded environment needs no flag

- **WHEN** a command runs in a project whose file records an environment, with none
  selected explicitly
- **THEN** the client targets the recorded environment

#### Scenario: A deploy that would strand the recorded deployment is refused

- **WHEN** a deploy or apply targets an environment other than the one recorded, in a
  project whose file records a deployment
- **THEN** the client refuses, names the environment the deployment lives on, and
  reports that `freepod init --force` on the other environment points the project there
- **AND** no deployment is created or modified

#### Scenario: A project with nothing to strand follows the target

- **WHEN** init targets an environment other than the one recorded, in a project whose
  file records no deployment
- **THEN** the deployment is created on the targeted environment
- **AND** the project file records that environment together with the new deployment

### Requirement: Build outputs are never recorded in the project file

The project file SHALL hold declared intent only. The image reference produced by a
build SHALL NOT be written to it, and a file that holds `image` SHALL be refused by the
client before anything is sent.

#### Scenario: A successful deploy does not modify user values

- **WHEN** a deploy completes successfully and releases a newly built image
- **THEN** the project file is unchanged
- **AND** it contains no image field

#### Scenario: An image in the file

- **WHEN** a developer adds `image` to the project file and runs `freepod apply`
- **THEN** the client refuses, naming `image` as a build output, and sends nothing

## ADDED Requirements

### Requirement: The file is flat and names no routing

The file's keys other than `$schema`, `version`, `env` and `deployment` SHALL be the
deployment's metadata keys and the product's chart properties, side by side at the top
level. The file SHALL NOT group them under a `user_values` or other routing element.

#### Scenario: A file with a name and sign-in

- **WHEN** a developer adds `name` and `auth` to the file
- **THEN** both are top-level keys, and `freepod apply` sends both

### Requirement: The deployment pointer is the deployment's id

Once linked, the file SHALL record the deployment's id as the string value of
`deployment`. The pointer SHALL be either absent, when the project is unlinked, or a
string. It SHALL never be null, and the file SHALL NOT record the deployment's name.

#### Scenario: Renaming does not touch the file

- **WHEN** the deployment is renamed in the dashboard while its `name` is unmanaged
- **THEN** the project file is unchanged

#### Scenario: A null pointer is refused

- **WHEN** a format 2 file holds `"deployment": null`
- **THEN** the client reports the file as invalid and names the fix: remove the key

### Requirement: The schema reference serves editors

The client SHALL write `$schema` as the product's project schema URL on the file's
environment. It SHALL rewrite a `$schema` that points at another environment when it
records the environment.

#### Scenario: A dev project

- **WHEN** a project is initialized on the development environment
- **THEN** `$schema` points at the development environment's project schema for `custom`

### Requirement: A format 1 file is migrated on read

The client SHALL rewrite a format 1 file as format 2 the first time it reads it, and say
so. The pointer's id SHALL be kept and its name dropped. `user_values` keys other than
`hostname` and `image` SHALL become top-level keys, so the deployment owns its hostname.
A null pointer SHALL become an unlinked file.

#### Scenario: A deployed format 1 project with sign-in

- **WHEN** a format 1 file records a deployment and `user_values` of `{"hostname": "arkanoid", "auth": {"enabled": true}}`
- **THEN** the rewritten file holds `$schema`, `version: 2`, `deployment` and `auth`, and no `hostname`

#### Scenario: A format 1 project never deployed

- **WHEN** a format 1 file records `"deployment": null` and `user_values` of `{"hostname": "arkanoid"}`
- **THEN** the rewritten file is unlinked and holds no `hostname`
- **AND** the client names `freepod init` as the next step

## REMOVED Requirements

### Requirement: The deployment pointer records both identifier and name

**Reason**: The name is now owner-chosen and renamable, so a copy in the file goes
stale.

**Migration**: See "The deployment pointer is the deployment's id". Clients read the
name from the deployment when they need it.
