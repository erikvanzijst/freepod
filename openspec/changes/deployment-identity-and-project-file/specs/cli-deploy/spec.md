# Spec Delta

## MODIFIED Requirements

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

## ADDED Requirements

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

## REMOVED Requirements

### Requirement: A first deploy creates the deployment before building

**Reason**: `freepod init` creates the deployment.

**Migration**: Run `freepod init` before the first deploy. A format 1 file with no
deployment is migrated to an unlinked file, which deploy reports by naming `freepod init`.

### Requirement: A first deploy selects a free plan

**Reason**: Plan selection moves to `freepod init`, together with creation.

**Migration**: See cli-init, "Initialization creates the deployment".

### Requirement: A deployment deleted out of band can be recreated

**Reason**: `deploy --recreate` is replaced. `freepod init --force` creates a new
deployment and re-points the file, and `freepod init` in an unlinked project creates one
without being asked.

**Migration**: Use `freepod init --force` where `freepod deploy --recreate` was used.

### Requirement: A hostname is sent as entered and re-checked only when it changes

**Reason**: Deploy no longer sends a hostname unless the file owns one, and the platform
validates an owned hostname as it validates any chart value.

**Migration**: None needed. A hostname the file owns is applied and checked by the
platform.
