# cli-init Specification

## Purpose
Turning an ordinary directory into a Freepod project: discovering what a user-supplied
application deployment requires, collecting it interactively, and recording it — without
provisioning anything.

## Requirements

### Requirement: Initialization resolves the user-application product by slug

The client SHALL locate the product that runs tenant-supplied images by its stable slug
`custom`, using the platform's public product listing. It SHALL NOT identify the product
by display name.

When no such product is visible, the client SHALL report that this instance does not
offer user-supplied application deployments, rather than reporting a lookup failure.

#### Scenario: The product is resolved from the public listing

- **WHEN** initialization runs against an instance offering the `custom` product
- **THEN** the client reads that product's current template and its user values schema

#### Scenario: A missing product is explained in the user's terms

- **WHEN** no product with slug `custom` is visible
- **THEN** the client reports that this instance does not offer user-supplied
  deployments

### Requirement: Initialization prompts for every required value in the template schema

The client SHALL derive the questions it asks from the product template's user values
schema rather than from a hardcoded list, prompting for each property the schema marks
as required. Properties that are not required SHALL be skipped. The answers SHALL be
sent to the platform with the deployment's creation and SHALL NOT be written to the
project file.

Constraints the client can evaluate locally — pattern, length bounds, and enumerated
values — SHALL be checked before accepting an answer, and a rejected answer SHALL be
re-prompted. Constraints the client cannot evaluate SHALL be left to the platform.

#### Scenario: A new required field is collected without a client release

- **WHEN** the product template's schema declares a required property the client has
  never seen
- **THEN** initialization prompts for it and sends the answer with the creation

#### Scenario: An answer failing a schema constraint is re-prompted

- **WHEN** an answer violates the property's pattern or length bounds
- **THEN** the client explains the constraint and asks again

#### Scenario: Optional properties are not written

- **WHEN** the schema declares a property that is not required
- **THEN** initialization neither prompts for it, sends it, nor writes it to the project file

#### Scenario: A value the file holds is not asked

- **WHEN** an unlinked project file holds `hostname`
- **THEN** initialization uses it and does not prompt for a hostname

#### Scenario: Answers stay out of the file

- **WHEN** initialization completes
- **THEN** the project file holds no hostname or other answer

### Requirement: The hostname prompt offers the directory's name

The client SHALL offer, as the initial answer to the hostname prompt, the deployment's
name reduced to a single DNS label. When the platform reports that label unusable, the
client SHALL offer the first of `-2`, `-3` and so on appended to it that the platform
reports usable, checking at most five. The user can accept the offered label unchanged or
edit it. On an interactive terminal the offered name SHALL be pre-typed as editable input;
where line editing is unavailable it SHALL be presented as the prompt's default. When the
name reduces to nothing, no answer SHALL be offered, and a suggestion that was rejected
SHALL NOT be offered again.

#### Scenario: The directory's name is accepted as offered

- **WHEN** initialization runs in a directory named `My_App.v2`, the user accepts that
  as the name, and then accepts the offered hostname
- **THEN** the client creates the deployment with hostname `my-app-v2`, completed beneath
  the account's domain name

#### Scenario: A taken label is made unique

- **WHEN** the name is `Arkanoid` and the platform reports `arkanoid` unusable but `arkanoid-2` usable
- **THEN** the client offers `arkanoid-2`

#### Scenario: A rejected suggestion is not offered again

- **WHEN** the platform reports the offered name as unusable
- **THEN** the client asks again without offering an answer

### Requirement: A hostname is checked before it is recorded

The client SHALL check a candidate hostname against the platform's hostname check before
creating the deployment, and SHALL re-prompt when the platform reports it as unusable,
showing the reported reason.

The check SHALL be treated as advisory: the name is claimed only when the deployment is
created, so a conflict at creation SHALL be reported with its reason and the hostname
asked for again.

#### Scenario: An unusable hostname is re-prompted with its reason

- **WHEN** the platform reports the candidate hostname as unusable
- **THEN** the client shows the reason and asks for another name

#### Scenario: A usable hostname is recorded

- **WHEN** the platform reports the candidate hostname as usable
- **THEN** the client creates the deployment with it

#### Scenario: A hostname taken in between

- **WHEN** the creation is refused because the hostname was claimed after the check
- **THEN** the client shows the reason and asks for another hostname

### Requirement: Initialization does not destroy an existing project

The client SHALL refuse to initialize a project whose file records a deployment, unless
replacement is explicitly requested. When it is, the client SHALL create a new deployment
and point the file at it, keeping the file's other keys. It SHALL name the deployment it
unlinks and SHALL leave that deployment as it is.

A project file that records no deployment SHALL be initialized without being asked, and
its other keys SHALL be kept.

Initialization SHALL NOT be presented anywhere as the remedy for a missing or newly
required configuration value.

#### Scenario: An existing project file is protected

- **WHEN** initialization runs where the project file records a deployment
- **THEN** the client refuses, names the deployment, and states how to replace it

#### Scenario: Overwriting is explicit about what it discards

- **WHEN** initialization runs with replacement requested
- **THEN** the client names the deployment it unlinks, which keeps running and stays on
  the dashboard

#### Scenario: An unlinked project keeps its keys

- **WHEN** initialization runs where the project file holds `name` and `auth` but no deployment
- **THEN** a deployment is created, the file's `name` and `auth` are applied to it, and the file keeps both

### Requirement: A hostname without a dot is kept as an application label

The client SHALL identify the hostname property by its schema title, matched
case-insensitively, the same rule the platform uses. It SHALL lowercase the entered value
and send it to the platform as entered. A value without a dot is an application label,
which the platform completes beneath the account's handle. When the account holds a handle,
the client SHALL show the resulting address by appending the reported `suffix`.

#### Scenario: A bare label is kept as a label

- **WHEN** the user enters `Photos` and the account's suffix is `-alice.freepod.app`
- **THEN** the client creates the deployment with hostname `photos`
- **AND** the client shows `photos-alice.freepod.app` as the address it will have

#### Scenario: A fully-qualified name is left intact

- **WHEN** the user enters a hostname containing a dot
- **THEN** the client lowercases it and sends it as entered

### Requirement: Initialization asks for the deployment's name first

The client SHALL ask for the deployment's name before any other value, offering the
current directory's name unchanged as the initial answer. When the project file holds a
`name`, the client SHALL use it and not ask.

#### Scenario: Accepting the directory's name

- **WHEN** initialization runs in a directory named `arkanoid` and the user accepts the offered name
- **THEN** the deployment is created with name `arkanoid`

### Requirement: A name is checked against the caller's deployments before it is used

The client SHALL read the caller's live deployments on the target environment and
compare names case-insensitively. When the directory's name is taken, it SHALL offer the
first of ` 2`, ` 3` and so on appended to it that is free. A taken name SHALL be
refused before the hostname is asked for, and the check SHALL be treated as advisory,
as the hostname check is.

#### Scenario: A taken directory name is made unique

- **WHEN** initialization runs in a directory named `arkanoid` and the caller already has a deployment named `Arkanoid`
- **THEN** the client offers `arkanoid 2`

#### Scenario: A name in use

- **WHEN** the user enters a name that one of their live deployments already has
- **THEN** the client reports that the name is in use and asks again, before asking for a hostname

#### Scenario: A taken name in the file

- **WHEN** an unlinked project file holds a `name` one of the caller's live deployments already has
- **THEN** initialization fails, naming the deployment, before anything is created

#### Scenario: A name taken in between

- **WHEN** the creation is refused with `name_in_use` because the name was taken after the check
- **THEN** the client reports it and asks for another name

### Requirement: Initialization can run without prompts

`freepod init` SHALL accept `--name` and `--hostname`, and SHALL ask only for what they do
not give. Without a terminal, a value that is neither given nor read from standard input
SHALL fail the command, naming the option, before anything is created.

#### Scenario: An agent initializes a project

- **WHEN** `freepod init --name Arkanoid --hostname arkanoid` runs without a terminal, and the template requires nothing else
- **THEN** the deployment is created and the project file written without any prompt

### Requirement: Initialization creates the deployment

After collecting its answers, initialization SHALL perform the checks a first deploy
performs: terms, handle and a free plan. It SHALL then create the deployment on the
canonical template, with no image, so that it serves the product's placeholder. It SHALL
return once the creation is accepted, without waiting for the first reconcile, and SHALL
say that the deployment is being provisioned in the background.

#### Scenario: Init claims the hostname

- **WHEN** initialization completes
- **THEN** a deployment with the chosen name and hostname exists
- **AND** its hostname is no longer usable by anyone else

#### Scenario: Init does not wait for provisioning

- **WHEN** the platform accepts the creation
- **THEN** the client writes the project file and exits without waiting for the deployment to become ready
- **AND** it reports the address and that the deployment is still being provisioned

#### Scenario: Vars before the first deploy

- **WHEN** a developer runs `freepod var set` right after initialization, while the deployment is provisioning
- **THEN** the var is accepted

#### Scenario: Terms not accepted

- **WHEN** the account has not accepted the current terms
- **THEN** initialization fails before creating anything and names how to accept them

### Requirement: Initialization claims an unlinked file's keys in the create

When an unlinked project file holds keys, the create SHALL carry them as apply sends
them, with the file's keys as `managed_fields`, so that one request creates the
deployment and claims its fields.

#### Scenario: An unlinked file with a name and sign-in

- **WHEN** initialization runs where an unlinked file holds `name` and `auth`
- **THEN** one create request carries both, and the created deployment's managed fields are `name` and `auth`

### Requirement: Initialization writes only the pointer

Once the platform accepts the creation, the client SHALL write the project file holding
`$schema`, `version`, the deployment's id and, when it is not the default, the
environment, together with any keys a pre-existing file held. If writing fails, the
client SHALL report the created deployment's name and that `freepod link` records it.

#### Scenario: The file after init

- **WHEN** initialization completes on the default environment in a directory with no project file
- **THEN** `.freepod.json` holds exactly `$schema`, `version` and `deployment`

#### Scenario: The file cannot be written

- **WHEN** the deployment was created but the project file cannot be written
- **THEN** the client reports the deployment's name and that `freepod link <name>` records it
