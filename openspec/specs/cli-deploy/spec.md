# cli-deploy Specification

## Purpose
The deploy command's contract: what it checks before spending effort, in what order it
does the expensive parts, and how it creates or updates the deployment that serves the
built image.
## Requirements
### Requirement: Deploy validates against current platform state before doing expensive work

Before packing or building anything, the client SHALL establish the authenticated
account, read the user-application product's current template, and — when a deployment
is already recorded — read that deployment. A deployment recorded in the project file
but absent from the platform SHALL be reported at this point, before any archive is
built.

#### Scenario: A deleted deployment is reported before a build is spent

- **WHEN** the deployment recorded in the project file no longer exists
- **THEN** the client reports it and names how to recreate the deployment
- **AND** no archive is packed and no build is created

#### Scenario: Preflight precedes packing

- **WHEN** a deploy runs
- **THEN** all preflight reads complete before the archive is packed

### Requirement: A newly required value is collected by prompting, not by re-initializing

When the product template requires a value the project file does not carry, the client
SHALL prompt for it using the same rules initialization uses, record it in the project
file, and continue the deploy. It SHALL NOT direct the user to re-initialize the
project, because re-initialization discards the deployment pointer.

Where no prompt is possible, the client SHALL fail and name the missing value.

#### Scenario: A template that gained a required field costs one question

- **WHEN** the product's current template requires a value absent from the project file
- **THEN** the client prompts for it, records it, and continues
- **AND** the deployment pointer is preserved

#### Scenario: A non-interactive run fails with the field named

- **WHEN** a required value is missing and no prompt can be presented
- **THEN** the client fails and names the missing value

### Requirement: The hostname is re-checked only when it changes

The client SHALL check the hostname against the platform only when it is new or has
changed relative to the recorded deployment. It SHALL NOT re-check an unchanged
hostname.

The platform's hostname check does not exclude the deployment that already holds the
name, so re-checking an unchanged hostname would report it as in use by its own
deployment. The check also performs live name resolution for hostnames outside the
platform's own domains, which is slow and can fail transiently.

A bare label in the project file SHALL be completed into an FQDN beneath the account's own
subdomain — `<label>.<subdomain>.<domain>` — rather than beneath a platform wildcard domain.
The client SHALL learn the subdomain and the domain from the platform at runtime and SHALL
NOT carry either as a constant. A value already containing a dot SHALL be treated as a
complete FQDN and left alone, so a custom domain still works.

#### Scenario: An unchanged hostname is not re-checked

- **WHEN** a deploy runs and the project file's hostname matches the deployment's
- **THEN** the client performs no hostname check

#### Scenario: A changed hostname is checked before packing

- **WHEN** the project file's hostname differs from the deployment's
- **THEN** the client checks it before packing
- **AND** stops with the reported reason when it is unusable

#### Scenario: A bare label completes under the account's address

- **WHEN** the project file's hostname is `photos`, the account holds `alice`, and the
  platform domain is `freepod.eu`
- **THEN** the client submits `photos.alice.freepod.eu`

#### Scenario: A full FQDN is left alone

- **WHEN** the project file's hostname is `photos.example.com`
- **THEN** the client submits it unchanged and the custom-domain path applies

### Requirement: The image is built before the deployment is created or updated

The client SHALL complete the build and obtain its image reference before creating or
updating the deployment, and SHALL supply that image with the creation request when
creating.

Creating first would roll out the platform's placeholder image and then roll out the
real one, and would leave a newly created deployment in a state that refuses updates.

#### Scenario: A first deploy performs a single rollout

- **WHEN** a project is deployed for the first time
- **THEN** the deployment is created carrying the built image
- **AND** only one rollout occurs

### Requirement: A first deploy selects a free plan

When creating a deployment, the client SHALL read the product's plans and select the
first plan whose current plan template carries a zero price. When no such plan exists,
the client SHALL refuse and state that only free plans are supported.

#### Scenario: The free plan is selected automatically

- **WHEN** the product offers a plan whose current template carries a zero price
- **THEN** the client creates the deployment against that plan's current template

#### Scenario: An instance with no free plan is refused clearly

- **WHEN** no plan's current template carries a zero price
- **THEN** the client refuses and states that only free plans are supported
- **AND** creates nothing

### Requirement: A deployment always targets the product's canonical template

The client SHALL submit the product's current template as the deployment's desired
template, on creation and on update alike. It SHALL NOT pin a deployment to the template
it was created against.

When the product's current template differs from the deployment's, the client SHALL
report the move rather than performing it silently.

#### Scenario: An advanced product template is adopted and announced

- **WHEN** the product's current template is newer than the deployment's
- **THEN** the update targets the product's current template
- **AND** the client reports the template change before applying it

#### Scenario: An unchanged template is not announced

- **WHEN** the product's current template matches the deployment's
- **THEN** the update targets that same template and reports no change

### Requirement: User values are submitted as a complete document

When the client supplies user values on an update, it SHALL supply the complete set —
the project file's declared values together with the built image reference — because the
platform replaces the stored values wholesale rather than merging them field by field.

Consequently a value edited in the project file SHALL take effect on the next deploy.

#### Scenario: A partial document is never sent

- **WHEN** the client updates a deployment with a new image
- **THEN** the submitted user values also carry every value declared in the project file

#### Scenario: An edited value is applied by the next deploy

- **WHEN** a user changes a declared value in the project file and deploys
- **THEN** the deployment reflects the changed value

### Requirement: Deploy waits for a deployment that is not ready to update

The platform accepts an update only while a deployment is settled. When the recorded
deployment is mid-rollout, the client SHALL wait, reporting the current status, until it
settles or the configured timeout elapses.

#### Scenario: An in-progress rollout is waited out

- **WHEN** the recorded deployment is provisioning at release time
- **THEN** the client waits, showing its status, and proceeds once it settles

#### Scenario: A conflicting update is reported for what it is

- **WHEN** the platform refuses the update because an operation is already in progress
- **THEN** the client reports that another operation is in progress

#### Scenario: A refusal is attributed by its reason, not by its status

- **WHEN** the platform refuses the release with a conflict status
- **THEN** the client reports the specific reason the platform gave
- **AND** suggests retrying only for the reasons a retry could resolve

#### Scenario: Stored values that no longer satisfy the target template are named as such

- **WHEN** the release is refused because the deployment's values fail the target
  template's schema
- **THEN** the client reports that the values no longer satisfy the template being moved
  to, naming the move
- **AND** does not present it as a transient conflict worth retrying

#### Scenario: A broken template schema is not blamed on the user

- **WHEN** the release is refused because the target template's own schema is invalid
- **THEN** the client reports a platform-side defect
- **AND** does not suggest the user change their configuration

#### Scenario: A hostname conflict at release is attributed correctly

- **WHEN** the platform refuses the update because the hostname is in use
- **THEN** the client reports that another deployment holds the hostname

### Requirement: The rollout is followed to a terminal state and reported

After creating or updating a deployment, the client SHALL poll it until its status is
terminal, and SHALL distinguish its own rollout from a previous one using the generation
returned by the create or update response.

On success the client SHALL report the address the application is served on. On failure
it SHALL report the platform's recorded error.

#### Scenario: A successful deploy reports the live address

- **WHEN** the rollout reaches a ready status
- **THEN** the client reports success and the deployment's address

#### Scenario: A failed rollout reports the platform's error

- **WHEN** the rollout reaches an error status
- **THEN** the client reports the deployment's recorded error

#### Scenario: A stale ready status is not mistaken for success

- **WHEN** polling begins while the deployment still shows the previous rollout's ready
  status
- **THEN** the client continues waiting until the status reflects its own generation

### Requirement: A deployment deleted out of band can be recreated

The client SHALL provide a way to discard the recorded deployment pointer and create a
new deployment for the project, so that a deployment removed on the platform does not
require editing the project file by hand.

#### Scenario: Recreation replaces the pointer

- **WHEN** a deploy runs with recreation requested
- **THEN** the client creates a new deployment and records its identifier and name

### Requirement: Deploy can roll a deployment without rebuilding it
`freepod deploy --no-build` SHALL create a release from the deployment's current image,
skipping the project archive upload and the build. This is what applies a staged
configuration change, and it also rolls a deployment whose source has not changed.

The command SHALL carry the applied release's build reference forward: it SHALL submit
the same image and the same build the applied release named, so that the new release
still records which build produced the code it is running.

`--no-build` SHALL be refused when the deployment has no applied release to take an image
from.

#### Scenario: Applying a staged var change
- **WHEN** a developer runs `freepod deploy --no-build` on a deployment with staged vars
- **THEN** a release is created from the current image, with no build
- **AND** the staged vars take effect

#### Scenario: The build reference is preserved
- **WHEN** `freepod deploy --no-build` rolls a deployment whose applied release named a
  build
- **THEN** the new release names the same build

#### Scenario: No image to roll
- **WHEN** a developer runs `freepod deploy --no-build` on a deployment that has never
  been applied
- **THEN** the command fails and explains that there is nothing to roll
