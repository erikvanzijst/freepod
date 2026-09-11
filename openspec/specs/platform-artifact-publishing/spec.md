# platform-artifact-publishing Specification

## Purpose

Defines where the platform's deployable artifacts — the product Helm charts and the
platform images their default values reference — are published, on what tags, at what
visibility, and what a template may reference. The artifacts the reconciler renders into
Kubernetes objects are the most privileged inputs the platform consumes, so where they
come from is a property of the platform rather than of whoever last packaged one.

## Requirements

### Requirement: Platform artifacts are published to the platform's public registry
Every Helm chart the platform deploys, and every platform-owned image referenced by a
chart's default values, MUST be published to the platform's public artifact registry —
the same registry that holds the platform's own container images.

A platform artifact MUST NOT be served from a registry that is local to one environment,
reachable only from a private network, or otherwise unable to serve every consumer:
CI, the reconciler, the kubelet, and an operator working from anywhere. An artifact that
only one network can reach cannot be published by the same path that builds it, cannot be
recovered when its host is rebuilt, and makes a release an act performed by a person
rather than by the publishing path.

#### Scenario: A chart is published where every consumer can reach it
- **WHEN** a product chart is published
- **THEN** it is retrievable from the platform's public artifact registry by any consumer, without access to a private network

#### Scenario: A template references the public registry
- **WHEN** a product template declares a chart reference
- **THEN** that reference names the platform's public artifact registry

#### Scenario: An environment-local registry is not a publication target
- **WHEN** a chart or a chart-referenced platform image is proposed for publication to a registry reachable only from one environment or network
- **THEN** that is not a valid publication target for a platform artifact

### Requirement: A published version is immutable
A publishing path MUST refuse to overwrite a version the registry already holds, and MUST
fail rather than succeed silently when asked to.

A change to a chart or a platform image is a new version, and consumers are repointed at
it. The guarantee MUST be enforced by the publishing path rather than only documented,
because a mutated tag changes what a deployment renders or runs with nothing in the
repository having moved.

A publishing path MUST also offer a mode in which an already-published version is a
no-op rather than a failure, so that an automated publish can run on every merge and
land exactly when a version changes.

#### Scenario: Re-publishing an existing version is refused
- **WHEN** a publish is attempted for a version the registry already holds
- **THEN** it fails and the published artifact is left untouched

#### Scenario: An unchanged version is a no-op for automation
- **WHEN** an automated publish runs in skip-if-published mode and the version is already published
- **THEN** it reports the artifact as already published and succeeds without publishing

#### Scenario: A bumped version publishes
- **WHEN** an automated publish runs and the declared version is not yet in the registry
- **THEN** the artifact is published under that version

### Requirement: The published tag comes from the artifact's declared version
A published artifact's tag MUST be derived from a version declaration that lives in the
repository beside the artifact's source — a chart's own `Chart.yaml` version, or a
version file in an image's build context — and MUST NOT be supplied as an argument at
publish time.

A version is therefore a reviewable edit, and what a given tag contains can be determined
from the repository alone.

#### Scenario: Tag is derived, not typed
- **WHEN** an artifact is published
- **THEN** the tag it carries is the version declared in its source, and no publish-time argument can override it

#### Scenario: A consumer pins an exact version
- **WHEN** a template or a chart default references a platform artifact
- **THEN** it names an exact version rather than a moving tag

### Requirement: Publishing runs unattended from the repository
Publishing MUST be performed by a scripted path checked into the repository, runnable by
continuous integration with no access to any private network and no operator workstation
in the loop.

Publication MUST be triggered by a merge to the default branch, so that a version landing
in the repository and a version landing in the registry are the same event.

#### Scenario: CI publishes on merge
- **WHEN** a change that bumps a chart version or a platform image version merges to the default branch
- **THEN** continuous integration publishes that artifact without manual intervention

#### Scenario: No private-network dependency
- **WHEN** the publishing path runs on a hosted runner with no route to any private network
- **THEN** it completes successfully

### Requirement: Platform artifacts are anonymously pullable and carry no secrets
Every published platform artifact MUST be readable without credentials, and MUST contain
no credential, key, or tenant data.

The reconciler installing a chart and the kubelet pulling a chart-default image MUST both
succeed with no pull secret and no registry login configured. A newly published artifact
that is not anonymously readable is a defect in the release, not a configuration step for
each consumer: a registry that defaults a new package to private requires that visibility
be set once, at publication, as part of publishing it.

#### Scenario: A chart installs with no credentials
- **WHEN** the reconciler installs a published chart
- **THEN** the pull succeeds without any registry credential

#### Scenario: A chart-default image pulls with no pull secret
- **WHEN** a deployment renders a chart default image reference and the kubelet pulls it
- **THEN** the pull succeeds without an image pull secret

#### Scenario: A private package is a release defect
- **WHEN** a newly published artifact is not anonymously readable
- **THEN** the release is incomplete until its visibility is corrected

### Requirement: Platform artifacts are retrieved over verified TLS
Every consumer of a platform artifact MUST verify the registry's TLS certificate, and no
consumer may disable certificate verification to retrieve one.

A registry that can only be used by disabling verification is therefore not a valid
publication target, and the requirement holds for the reconciler's chart install, for the
publishing path, and for any documented operator command.

#### Scenario: The reconciler verifies the chart registry
- **WHEN** the reconciler installs or upgrades a release from an OCI chart reference
- **THEN** it retrieves the chart with TLS verification enabled

#### Scenario: Documented commands do not disable verification
- **WHEN** an operator follows a documented publish or pull command for a platform artifact
- **THEN** that command does not disable TLS verification

### Requirement: A retired registry serves no platform artifact
When platform artifacts move, the migration MUST be complete before the previous
location is retired: no product's current template, no template a live deployment desires
or runs, and no live deployment may still resolve a chart or a chart-default image from
it. A template row that is none of these is history rather than configuration — no
reconcile resolves it — and is not required to be rewritten or deleted.

Because a chart reference is part of a template's identity, moving it produces a new
template version rather than mutating the existing one, and every deployment on the old
version MUST be moved to the new one explicitly. Retirement MUST be the last step. The
repositories left behind are not required to be deleted: once nothing resolves from them
they are inert.

#### Scenario: No resolvable template references the retired location
- **WHEN** the migration is complete
- **THEN** no product's current template and no template a live deployment desires or runs — catalog-declared or database-authored — carries a chart reference or a chart-default image reference to the retired registry

#### Scenario: A historical template row is exempt
- **WHEN** a template row is neither a product's current template nor desired or run by any live deployment
- **THEN** it may still name the retired registry, because no reconcile resolves it

#### Scenario: No live deployment resolves from the retired location
- **WHEN** the migration is complete
- **THEN** every live deployment resolves its chart and its chart-default image from the platform's public artifact registry

#### Scenario: Deployments keep serving during the migration
- **WHEN** a deployment has not yet been moved to the template version carrying the new reference
- **THEN** it continues to run and to reconcile against its current template
