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
as required. Properties that are not required SHALL be skipped and SHALL NOT be written.

Constraints the client can evaluate locally — pattern, length bounds, and enumerated
values — SHALL be checked before accepting an answer, and a rejected answer SHALL be
re-prompted. Constraints the client cannot evaluate SHALL be left to the platform.

#### Scenario: A new required field is collected without a client release

- **WHEN** the product template's schema declares a required property the client has
  never seen
- **THEN** initialization prompts for it and records the answer

#### Scenario: An answer failing a schema constraint is re-prompted

- **WHEN** an answer violates the property's pattern or length bounds
- **THEN** the client explains the constraint and asks again

#### Scenario: Optional properties are not written

- **WHEN** the schema declares a property that is not required
- **THEN** initialization neither prompts for it nor writes it to the project file

### Requirement: A hostname without a domain is completed from a platform domain

The client SHALL identify the hostname property by its schema title, matched
case-insensitively, which is the same rule the platform uses to derive a deployment's
hostname. It SHALL lowercase the entered value, and when the entered value contains no
dot, SHALL append the platform's first wildcard domain to form a fully-qualified name.

#### Scenario: A bare label becomes a platform subdomain

- **WHEN** the user enters a hostname containing no dot
- **THEN** the client appends the platform's first wildcard domain
- **AND** shows the resulting fully-qualified name

#### Scenario: A fully-qualified name is left intact

- **WHEN** the user enters a hostname containing a dot
- **THEN** the client lowercases it and uses it as entered

### Requirement: The hostname prompt offers the directory's name

The client SHALL offer the current directory's name, reduced to a single DNS label, as
the initial answer to the hostname prompt, which the user can accept unchanged or edit.
On an interactive terminal the offered name SHALL be pre-typed as editable input; where
line editing is unavailable it SHALL be presented as the prompt's default. When the name
reduces to nothing, no answer SHALL be offered, and a suggestion that was rejected SHALL
NOT be offered again.

#### Scenario: The directory's name is accepted as offered

- **WHEN** initialization runs in a directory named `My_App.v2` and the user accepts the
  offered answer
- **THEN** the client records `my-app-v2` completed beneath the account's domain name

#### Scenario: A rejected suggestion is not offered again

- **WHEN** the platform reports the offered name as unusable
- **THEN** the client asks again without offering an answer

### Requirement: A hostname is checked before it is recorded

The client SHALL check a candidate hostname against the platform's hostname check before
writing it to the project file, and SHALL re-prompt when the platform reports it as
unusable, showing the reported reason.

The check SHALL be treated as advisory: the name is only claimed when a deployment is
created, so a later conflict remains possible and SHALL be handled at that point.

#### Scenario: An unusable hostname is re-prompted with its reason

- **WHEN** the platform reports the candidate hostname as unusable
- **THEN** the client shows the reason and asks for another name

#### Scenario: A usable hostname is recorded

- **WHEN** the platform reports the candidate hostname as usable
- **THEN** it is written to the project file

### Requirement: Initialization does not write to the platform

Initialization SHALL perform reads only. It SHALL NOT create a deployment or any other
server-side resource. Creation is the responsibility of the deploy command, so that a
failure while writing the project file cannot leave a provisioned resource the user
cannot see.

#### Scenario: No resource is created

- **WHEN** initialization completes
- **THEN** the user's set of deployments is unchanged

#### Scenario: A failed write leaves nothing behind

- **WHEN** the project file cannot be written
- **THEN** no deployment or other resource exists as a result of the command

### Requirement: Initialization does not destroy an existing project

The client SHALL refuse to overwrite an existing `.freepod.json` unless overwriting is
explicitly requested. When overwriting is requested, it SHALL discard the existing file
in full, including its deployment pointer.

Because overwriting discards the deployment pointer, initialization SHALL NOT be
presented anywhere as the remedy for a missing or newly required configuration value.

#### Scenario: An existing project file is protected

- **WHEN** initialization runs in a directory that already has a project file
- **THEN** the client refuses and states how to overwrite deliberately

#### Scenario: Overwriting is explicit about what it discards

- **WHEN** initialization runs with overwriting requested
- **THEN** the client warns that the existing deployment pointer will be discarded

