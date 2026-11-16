# cli-deploy Specification

## Purpose
The deploy command's contract: what it checks before spending effort, in what order it
does the expensive parts, and how it creates or updates the deployment that serves the
built image.

## Requirements

### Requirement: Deploy validates against current platform state before doing expensive work

Before packing or building anything, the client SHALL establish the authenticated
account, read the user-application product's current template, and read the deployment
the project file records. A project that records no deployment, or whose recorded
deployment is absent from the platform, SHALL be reported at this point, before any
archive is built.

#### Scenario: A deleted deployment is reported before a build is spent

- **WHEN** the deployment recorded in the project file no longer exists
- **THEN** the client reports it and names `freepod init --force` and `freepod link`
- **AND** no archive is packed and no build is created

#### Scenario: An unlinked project is reported before a build is spent

- **WHEN** a deploy runs in a project whose file records no deployment
- **THEN** the client names `freepod init` and `freepod link`, and builds nothing

#### Scenario: Preflight precedes packing

- **WHEN** a deploy runs
- **THEN** all preflight reads complete before the archive is packed

### Requirement: A newly required value is collected by prompting, not by re-initializing

When the product template requires a value that neither the deployment nor the project
file carries, the client SHALL prompt for it using the same rules initialization uses,
send it with the deploy's release, and continue. It SHALL NOT write it to the project
file, and SHALL NOT direct the user to re-initialize the project.

Where no prompt is possible, the client SHALL fail and name the missing value.

#### Scenario: A template that gained a required field costs one question

- **WHEN** the product's current template requires a value the deployment does not have
- **THEN** the client prompts for it, sends it with the release, and continues
- **AND** the project file is unchanged

#### Scenario: A non-interactive run fails with the field named

- **WHEN** a required value is missing and no prompt can be presented
- **THEN** the client fails and names the missing value

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

The client SHALL submit a deploy as one update, built as apply builds it: the file's
identity keys, the deployment's stored chart values with the file's chart keys over
them, and the file's keys as `managed_fields`. The update SHALL also carry the product's
current template, the successful build, and the build's image as the chart's `image`
value. The platform SHALL apply them in one release. `image` SHALL NOT be listed in
`managed_fields`.

Consequently a key edited in the project file SHALL take effect on the next deploy, in
the same release as the new code.

#### Scenario: A partial document is never sent

- **WHEN** the client deploys a new build
- **THEN** the update carries every chart value of the deployment, with every key of the project file over them

#### Scenario: One release for the file and the build

- **WHEN** a developer edits `auth` in the project file and deploys
- **THEN** exactly one release is created, running the new build with the edited `auth`

#### Scenario: An edited value is applied by the next deploy

- **WHEN** a user changes a key in the project file and deploys
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

#### Scenario: A release to a deployment held for maintenance

- **WHEN** the platform refuses the update with code `under_maintenance`
- **THEN** the client says the deployment is held for platform maintenance and is worth retrying later
- **AND** says the built image is reused by a re-run

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

### Requirement: Deploy can roll a deployment without rebuilding it
`freepod deploy --no-build` SHALL be an alias of `freepod apply`. It SHALL skip the
project archive upload and the build, apply the project file, and roll out pending vars
from the deployment's current image.

#### Scenario: Applying a staged var change
- **WHEN** a developer runs `freepod deploy --no-build` on a deployment with staged vars
- **THEN** a release is created from the current image, naming the build it runs
- **AND** the staged vars take effect

#### Scenario: The build reference is preserved
- **WHEN** `freepod deploy --no-build` rolls a deployment whose applied release named a
  build
- **THEN** the new release names the same build

#### Scenario: No image to roll
- **WHEN** a developer runs `freepod deploy --no-build` on a deployment that has never
  been released with a build, and the file and vars hold no change
- **THEN** the command reports that nothing changed

### Requirement: An old-format hostname in the project file is rewritten to its label

When the project file's hostname has the form `<label>.<x>.freepod.eu` or
`<label>.<x>.dev.freepod.eu`, the client SHALL replace it with `<label>`, save the project
file, and print one line saying so, before any hostname check or submission. This pattern is
fixed in the client: it only corrects the client's own earlier output.

#### Scenario: A production hostname is rewritten

- **WHEN** the project file's hostname is `photos.alice.freepod.eu`
- **THEN** the client rewrites it to `photos`, saves the file, and says so

#### Scenario: A development hostname is rewritten

- **WHEN** the project file's hostname is `notes.bob.dev.freepod.eu`
- **THEN** the client rewrites it to `notes`

#### Scenario: Other hostnames are untouched

- **WHEN** the project file's hostname is `photos`, `photos-alice.freepod.app`,
  `grafana.freepod.eu`, or `photos.example.com`
- **THEN** the client leaves it unchanged

### Requirement: The first deploy replaces the placeholder

A deploy into a deployment that has never run a build SHALL proceed like any other
deploy. When the deployment is still being provisioned, the client SHALL wait until it
settles before releasing, then follow the rollout until the app serves the build in place
of the placeholder.

#### Scenario: The first deploy after init

- **WHEN** a developer runs `freepod deploy` in a project just initialized
- **THEN** the build is released, the deployment runs it, and the client prints its address

#### Scenario: Provisioning still in flight

- **WHEN** the build finishes while the deployment's first reconcile is still running
- **THEN** the client waits for the deployment to settle, then releases the build
