# cli-environments Specification

## Purpose
How the client chooses which Freepod instance it is talking to, and why that choice is
a closed set of named environments rather than a caller-supplied address.
## Requirements
### Requirement: The client targets one of two named environments

The client SHALL support exactly two environments, `prod` and `dev`, each carrying its
own API base address, OAuth2 client identifier, and issuer. The environment SHALL be
selectable per invocation, SHALL otherwise be taken from the project file in the working
directory, and SHALL default to `prod` where neither answers.

The client SHALL NOT accept a caller-supplied API base address. An access token is bound
by its audience to exactly one environment, so an arbitrary address would additionally
require the issuer and client identifier to be discovered, which the platform does not
publish.

#### Scenario: Production is the default target

- **WHEN** a command runs with no environment selected, in a directory that holds no
  project
- **THEN** the client targets the production environment

#### Scenario: The environment can be selected explicitly

- **WHEN** a command runs with the environment selected as `dev`
- **THEN** the client targets the development API, client identifier, and issuer

#### Scenario: The environment can be selected through the environment variable

- **WHEN** `FREEPOD_ENV` names an environment, no explicit selection is made, and the
  working directory holds no project
- **THEN** the client targets that environment

#### Scenario: An unknown environment is refused

- **WHEN** a command runs with an environment name that is not `prod` or `dev`
- **THEN** the client refuses with a usage error naming the accepted values

### Requirement: A project selects the environment it lives on

Where the working directory or an ancestor holds a project file, the client SHALL target
the environment that file records unless an environment is selected explicitly. The file
SHALL outrank `FREEPOD_ENV`, because it is the most specific statement of where the
project lives and a deployment identifier minted on one environment has no meaning on
the other: a global default must not pull a command away from the environment its
project was created on.

Resolving the environment this way SHALL NOT fail. The client reads the file for every
command, including those that do not otherwise touch a project, so a file that is
missing, unreadable, or records an environment this client does not recognize SHALL
leave the ordinary default in place rather than refuse. A command that needs the project
reports the problem itself.

#### Scenario: A project on the development environment needs no flag

- **WHEN** a command runs in a project whose file records `dev`, with no environment
  selected
- **THEN** the client targets the development environment

#### Scenario: An explicit selection outranks the project file

- **WHEN** a command runs in a project whose file records `dev`, with `prod` selected
  explicitly
- **THEN** the client targets the production environment

#### Scenario: The project file outranks the environment variable

- **WHEN** `FREEPOD_ENV` names one environment and the project file records another,
  with no explicit selection
- **THEN** the client targets the environment the project file records

#### Scenario: A project file that names no environment is on production

- **WHEN** `FREEPOD_ENV` names `dev` and the project file names no environment, with no
  explicit selection
- **THEN** the client targets the production environment

#### Scenario: An unusable project file does not refuse the command

- **WHEN** a command that does not require a project runs where the project file cannot
  be read or records an unrecognized environment
- **THEN** the client targets the default environment and the command proceeds

### Requirement: Only the default environment is visible to users

Production is the only environment end users have. The explicit environment selection
SHALL work but SHALL NOT appear in `--help`, and neither SHALL `FREEPOD_ENV`. Output,
prompts, and errors SHALL name an environment only when a non-default one is in use, so
a user on production never sees one named.

#### Scenario: The selection is absent from help but still accepted

- **WHEN** `freepod --help` is shown
- **THEN** it mentions neither `--env` nor `FREEPOD_ENV`
- **AND** `freepod --env dev <command>` still targets the development environment

#### Scenario: Production output names no environment

- **WHEN** any command runs against the production environment
- **THEN** its output names no environment, and any `freepod login` it suggests carries
  no `--env`

### Requirement: State is never shared between environments

The client SHALL keep credentials and project state separated per environment, so that
material obtained for one environment is never presented to the other.

#### Scenario: Credentials do not cross environments

- **WHEN** the client holds a credential for one environment and a command targets the
  other
- **THEN** the credential for the targeted environment is used, or authentication is
  requested for it
- **AND** the other environment's credential is never sent

#### Scenario: A token issued for one environment is rejected by the other

- **WHEN** an access token issued for the development environment reaches the production
  API
- **THEN** the request is refused, because audience verification fails

