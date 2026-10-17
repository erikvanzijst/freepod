## ADDED Requirements

### Requirement: The worker stores a succeeded build's static-site verdict

When the worker records a build as `succeeded`, it SHALL store the static-site verdict
from that build's termination status in the same write as the image. It SHALL store
not a static site when the verdict is absent or is not an explicit yes. A malformed
verdict SHALL NOT change the build's outcome.

#### Scenario: A succeeded static-site build is recorded as one

- **WHEN** a build's Job succeeds and reports an image and a static site
- **THEN** the build is `succeeded` with its image, and records a static site

#### Scenario: A malformed verdict does not fail the build

- **WHEN** a build's Job succeeds and reports an image with a verdict that is not a
  boolean
- **THEN** the build is `succeeded` and records not a static site
