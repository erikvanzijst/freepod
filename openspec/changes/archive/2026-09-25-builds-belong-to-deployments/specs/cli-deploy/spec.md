## REMOVED Requirements

### Requirement: The image is built before the deployment is created or updated

**Reason**: A build now belongs to a deployment, so the deployment must exist before the
build is created. Creating first was avoided to spare a first deploy its placeholder
rollout; the placeholder is an appropriate landing page, and that saving no longer
outweighs a build that cannot name its deployment.

**Migration**: Replaced by "A first deploy creates the deployment before building".

## ADDED Requirements

### Requirement: A first deploy creates the deployment before building

When the project records no deployment, or recreation is requested, the client SHALL
create the deployment before packing, uploading or building anything, supplying no image,
so that the product serves its placeholder until the first build is released. The client
SHALL record the new deployment in the project file immediately after the platform
creates it, before any further step.

The client SHALL then build against that deployment and release the build into it,
exactly as on any later deploy, including waiting for the deployment to become ready
before updating it.

A first build that does not succeed SHALL leave the deployment in place and recorded, so
that the next deploy reuses it rather than creating another. The client SHALL say that
the deployment exists and name `freepod delete` as the way to remove it.

`freepod init` SHALL continue to write nothing to the platform.

#### Scenario: A first deploy creates, then builds, then releases

- **WHEN** a project with no recorded deployment is deployed
- **THEN** the deployment is created with no image and recorded in the project file
- **AND** the build is created against that deployment
- **AND** the build's image is released into it

#### Scenario: The pointer survives a failed first build

- **WHEN** a first deploy's build does not succeed
- **THEN** the project file still records the new deployment
- **AND** the client states that it exists and that `freepod delete` removes it
- **AND** the next deploy builds against that same deployment

#### Scenario: Recreation creates before building

- **WHEN** a deploy runs with recreation requested
- **THEN** the new deployment is created and recorded before the build is created against it
