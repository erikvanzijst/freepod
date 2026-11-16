# cli-link Specification

## Purpose
`freepod link`: pointing a project at a deployment that already exists, so a lost
project file, a fresh clone without one, or a second machine needs no new deployment.

## Requirements

### Requirement: Link records an existing deployment by name or id

`freepod link <name-or-id>` SHALL find the caller's live deployment on the target
environment whose id equals the argument, or whose name equals it when compared
case-insensitively. It SHALL record that deployment's id and the environment in the
project file.

#### Scenario: Linking by name

- **WHEN** a developer runs `freepod link arkanoid` and owns a deployment named `Arkanoid`
- **THEN** the project file points at that deployment

#### Scenario: No such deployment

- **WHEN** the argument matches none of the caller's live deployments
- **THEN** link fails, writes nothing, and names `freepod init`

### Requirement: Link without an argument offers a list to pick from

On an interactive terminal, `freepod link` without an argument SHALL list the caller's
live deployments on the target environment, each with its name, hostname and product,
and let the user move through them with the arrow keys and narrow them by typing. The
chosen deployment SHALL be linked as if it had been named. Without a terminal, link
without an argument SHALL fail and name the argument it needs. When the caller has no
deployments, link SHALL say so and name `freepod init`.

#### Scenario: Picking a deployment

- **WHEN** a developer runs `freepod link` on a terminal, types `ark` and presses Enter on `Arkanoid`
- **THEN** the project file points at `Arkanoid`

#### Scenario: An agent without a terminal

- **WHEN** `freepod link` runs without an argument and without a terminal
- **THEN** it fails, names `freepod link <name-or-id>`, and writes nothing

### Requirement: A new file recreates the deployment's managed fields

When no project file exists, link SHALL create one holding the pointer, the environment
when it is not the default, `$schema`, and every managed field of the deployment other
than `icon` with its current value, so that an apply right after it changes nothing. A
managed `icon` SHALL be left out, and link SHALL say that the icon has to be added back
to the file.

#### Scenario: Recovering a lost file

- **WHEN** a developer runs `freepod link arkanoid` where no `.freepod.json` exists, and the deployment's managed fields are `name` and `auth`
- **THEN** the new file holds `name` and `auth` with the deployment's values
- **AND** an immediate `freepod apply` reports that nothing changed

#### Scenario: A managed icon

- **WHEN** the linked deployment's managed fields include `icon`
- **THEN** the new file has no `icon`, and link says that the icon has to be added back to the file

### Requirement: Link keeps an existing file's keys and does not apply them

When a project file exists, link SHALL keep every other key of it and SHALL NOT send them
to the deployment. It SHALL report the keys that differ from the deployment, and the
managed fields the file does not hold, and name `freepod apply`.

#### Scenario: Relinking a file with a description

- **WHEN** a file holding `description` is linked to a deployment with a different description
- **THEN** the file keeps its description, the deployment is unchanged, and link names `freepod apply`

#### Scenario: A managed field the file lacks

- **WHEN** a file without `auth` is linked to a deployment whose `auth` is managed
- **THEN** link reports that the next `freepod apply` gives up `auth`

### Requirement: Link does not silently replace a pointer

When the project file already records a deployment, link SHALL refuse unless
replacement is requested explicitly. When replacement is requested, it SHALL name the
deployment it stops pointing at, which is left as it is.

#### Scenario: A project already linked

- **WHEN** link runs in a project whose file records a deployment, without `--force`
- **THEN** it refuses and states how to replace the pointer
