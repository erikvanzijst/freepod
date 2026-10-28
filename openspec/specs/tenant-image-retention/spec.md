# tenant-image-retention Specification

## Purpose
Which tenant images the platform keeps in its registry, how every other image is released
to garbage collection, and how a deployment write is kept from referencing an image that
is no longer there.

## Requirements

### Requirement: Retained images are derived from the release ledger
An owner's image SHALL be retained while its reference appears among the user values of a
retained release of one of that owner's deployments that has not been deleted.

A deployment's retained releases SHALL be its desired release, its applied release, and,
walking its earlier releases from the most recent, those carrying its two most recent
distinct owner images other than the desired and applied ones.

#### Scenario: The running image is retained
- **WHEN** a deployment's applied release carries an image
- **THEN** that image is retained

#### Scenario: A rollout in progress keeps both images
- **WHEN** a deployment's desired release carries a new image and its applied release an older one
- **THEN** both images are retained

#### Scenario: Two earlier images are retained
- **WHEN** a deployment has shipped five distinct images, the latest of which it is running
- **THEN** the latest and the two before it are retained, and the two oldest are not

#### Scenario: Redeploying one image counts once
- **WHEN** a deployment has had ten releases carrying the same earlier image, from configuration changes
- **THEN** that image takes one of the two earlier slots, not all of them

#### Scenario: A deleted deployment retains nothing
- **WHEN** a deployment is deleted
- **THEN** none of its releases retain any image

#### Scenario: An image shared between deployments
- **WHEN** an owner's image is no longer retained by the deployment that built it but is carried by the applied release of another of that owner's deployments
- **THEN** it is retained

### Requirement: Images are matched by value, as owner references
An image SHALL be recognized in user values by its value alone, wherever it appears, as a
reference to the owner's own image repository by digest. The rule SHALL NOT look up any
particular value key, and SHALL NOT depend on which build, if any, a release names.

#### Scenario: A release that names no build
- **WHEN** a release carries an owner image among its user values and names no build
- **THEN** the image is retained exactly as if the release had named its build

#### Scenario: A value that is not an owner image
- **WHEN** a release carries a value that is not a digest reference to its owner's image repository
- **THEN** that value retains nothing

### Requirement: Fresh builds are retained
An owner's build SHALL keep its image retained, whatever the ledger says, while the build is
not yet terminal or for a grace period after it succeeded, so that a build's image survives
the interval between the build finishing and a deployment write naming it.

#### Scenario: A build that just finished
- **WHEN** a build succeeded within the grace period and no release carries its image yet
- **THEN** its image is retained

#### Scenario: A build still pushing
- **WHEN** a build has pushed its image but has not yet been recorded as succeeded
- **THEN** its image is retained

#### Scenario: A build that was never deployed
- **WHEN** a build succeeded longer ago than the grace period and no retained release carries its image
- **THEN** its image is not retained

### Requirement: Retention is computed, never stored
Whether an image is retained SHALL be computed from the ledger and the builds each time it is
needed. No build, release or deployment SHALL carry a field recording that its image was
pruned, expired or retained.

#### Scenario: Nothing is written when an image leaves retention
- **WHEN** a later release pushes an image out of a deployment's retained releases
- **THEN** no column on any build, release or deployment is written to record it

### Requirement: Leaving retention is permanent
Once an image is not retained, no request SHALL make it retained again, other than a new
build that produces the same image. A rule that could re-admit an image would let a write
reference an image the prune had already removed.

#### Scenario: An old image is not brought back
- **WHEN** an image has left retention and a deployment write references it
- **THEN** the write is rejected, so the image stays outside retention

### Requirement: Images outside retention are untagged daily
Once a day, ahead of the registry's garbage collection, the platform SHALL remove from each
owner's image repository every tag whose image is not retained, and SHALL NOT remove any tag
whose image is retained.

#### Scenario: A superseded image is released to collection
- **WHEN** the prune runs and a tag's image is not retained
- **THEN** the tag is removed, and the next garbage collection reclaims what only it reached

#### Scenario: Two builds produced the same image
- **WHEN** two tags point at the same image and that image is retained by either build
- **THEN** both tags remain

#### Scenario: A tag with no build record
- **WHEN** a tag in an owner's repository names no build the platform knows
- **THEN** it is kept or removed by whether the image it points at is retained

#### Scenario: The cache is untouched
- **WHEN** the prune runs
- **THEN** no tag outside the owners' image repositories is removed

### Requirement: The prune never removes an image a concurrent build or write needs
The prune SHALL read the tags it will judge before it computes retention, and SHALL keep any
tag naming a build that is retained as fresh, so that a tag pushed or a release written while
it runs is never removed by a stale view.

#### Scenario: A build finishes during the prune
- **WHEN** a build pushes its image while the prune is running
- **THEN** that build's tag is not removed

#### Scenario: A deployment write during the prune
- **WHEN** a write creates a release carrying a retained image while the prune is running
- **THEN** that image's tags are not removed

### Requirement: The prune can be previewed
An operator SHALL be able to run the prune as a dry run that reports, per owner, the tags it
would remove and why the others are kept, and removes nothing.

#### Scenario: A dry run
- **WHEN** an operator runs the prune as a dry run
- **THEN** it reports what it would remove and no tag is removed

### Requirement: A deployment write may reference only retained images
A deployment create or update SHALL be rejected when its submitted user values carry an owner
image that is not retained, or when it names a build whose image is not retained. Retention is
judged as it stood before the write. The rejection SHALL tell the caller to rebuild.

#### Scenario: Rolling back within the window
- **WHEN** an update names a build whose image is one of the deployment's two earlier retained images
- **THEN** the update is accepted

#### Scenario: Rolling back past the window
- **WHEN** an update names a build whose image is no longer retained
- **THEN** the update is rejected, no release is created, and the error says to rebuild

#### Scenario: An old image submitted without its build
- **WHEN** an update submits, among its user values, an owner image that is no longer retained, naming no build
- **THEN** the update is rejected

#### Scenario: A configuration change
- **WHEN** an update changes only vars or other values, keeping the applied image
- **THEN** the update is accepted
