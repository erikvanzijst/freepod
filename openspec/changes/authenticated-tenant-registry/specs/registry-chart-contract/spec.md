## Purpose

What a product chart is handed so that it can run an image a tenant built: where the
registry is, and which credential the node should pull with. Both are platform facts that
differ per environment, and neither may originate with a tenant — which is what keeps a
tenant-supplied image reference from becoming a pointer at a registry of the tenant's
choosing.

## ADDED Requirements

### Requirement: The registry host reaches the chart as a system value
The registry a tenant image is pulled from MUST be supplied to the chart by the platform
at reconciliation, as a system value that tenant input cannot set or shadow.

It MUST NOT be a chart default. One chart serves every environment, and each environment
has its own registry, so a default in the chart's own values can only be correct for one
of them.

#### Scenario: The platform supplies the host
- **WHEN** a deployment is reconciled
- **THEN** the chart renders the image reference against the registry of the environment the deployment runs in

#### Scenario: Tenant input cannot redirect the pull
- **WHEN** a tenant supplies a value that would set or override the registry host
- **THEN** the rendered image reference still names the platform's registry

### Requirement: The chart composes the pull reference and proves ownership
A chart MUST compose the image it runs from the platform-supplied registry and the
tenant-supplied reference, and MUST refuse to render when the tenant-supplied reference
names a repository that is not the deployment owner's.

The tenant supplies a reference carrying the owner and the digest but no registry, so
composing it is where the two halves meet: withholding the host stops a tenant naming
another registry, and checking the owner stops a tenant naming another owner's repository.
The owner the check compares against MUST be supplied by the platform.

#### Scenario: An owner's own image renders
- **WHEN** a deployment supplies an image reference whose repository is its owner
- **THEN** the chart renders a pull reference combining the platform's registry with that reference

#### Scenario: Another owner's image is refused
- **WHEN** a deployment supplies an image reference whose repository is another owner
- **THEN** rendering fails with an error naming the mismatch

### Requirement: The chart references the pull credential by name only
A chart that runs a tenant image MUST reference the pull credential by the Secret name the
platform supplies as a system value, and MUST NOT receive or render credential material.

Naming a Secret keeps the credential out of the chart's values, out of the release
history the release object stores, and out of anything a rendering of the chart would
reveal.

#### Scenario: The rendered workload names the credential
- **WHEN** a deployment that runs a tenant image is rendered
- **THEN** its pod specification references the pull credential by name

#### Scenario: No credential material in chart values
- **WHEN** a deployment's rendered values and stored release are inspected
- **THEN** neither contains the pull credential's password

#### Scenario: A deployment with no tenant image needs no credential
- **WHEN** a deployment has no image yet and renders the platform's placeholder
- **THEN** it renders without requiring a tenant-registry pull credential
