# Spec Delta

## MODIFIED Requirements

### Requirement: A named build must belong to the deployment

A build reference is optional on every write. Where one is named, it SHALL exist and
SHALL belong to the deployment being created or updated; a request naming any other
build SHALL be rejected. On creation, where no deployment exists yet, no build can
belong to it, so a creation request naming a build SHALL be rejected.

A named build's image SHALL also be retained, as `tenant-image-retention` defines it; a
request naming a build whose image is no longer retained SHALL be rejected, distinguishably
from one naming a build that does not belong, so the caller can be told to rebuild.

Validation SHALL occur at the write, where the caller can still be told, and SHALL NOT be
deferred to the reconciler.

Belonging and retention are the **only** conditions. The platform SHALL NOT require
agreement between a named build and any value in the deployment's user values, and SHALL
NOT require a build to be named because some value is present.

`image` is a value of one product's chart, not a platform-wide concept: most products
build nothing, charts choose their own value names, and a single build or release may
come to carry more than one image. A rule tying the ledger to a particular chart's value
key would make the release record an artifact of `custom`'s schema. An image reference
could not identify a build on its own in any case: it is content-addressed, so more than
one build can produce the same reference.

#### Scenario: A build of another deployment

- **WHEN** an update names a build belonging to a different deployment, even one the caller owns
- **THEN** the request is rejected, and no provenance from it is recorded

#### Scenario: A build that does not exist

- **WHEN** a request names a build that does not exist
- **THEN** the request is rejected, indistinguishably from one belonging to another deployment

#### Scenario: A build named on creation

- **WHEN** a deployment creation request names a build
- **THEN** the request is rejected and no deployment is created

#### Scenario: A build whose image is no longer retained

- **WHEN** an update names a build of the deployment whose image is no longer retained
- **THEN** the request is rejected, no release is created, and the error says to rebuild

#### Scenario: An image reused without its build

- **WHEN** an update submits a retained image produced by another deployment's build, naming no build
- **THEN** the request is accepted and the release records no build

#### Scenario: No build is named

- **WHEN** a deployment is written with no build named, and every owner image among its user values is retained
- **THEN** the request is accepted and the release records no build
