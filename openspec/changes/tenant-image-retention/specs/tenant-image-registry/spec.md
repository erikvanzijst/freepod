# Spec Delta

## MODIFIED Requirements

### Requirement: Storage is reclaimable
The registry MUST permit deletion and MUST run a scheduled garbage collection that
reclaims blobs no manifest references.

Garbage collection MUST NOT remove a manifest that anything could still deploy. Every
pushed image is anchored by a tag for exactly this reason, so a collection pass that
removes untagged manifests cannot strand a deployment that references an image by digest.
An image's anchoring tag MUST stay in place while the image is retained, and is removed
once retention releases it, which is what makes the image's storage reclaimable.

#### Scenario: Unreferenced blobs are reclaimed
- **WHEN** garbage collection runs after content has become unreferenced
- **THEN** the storage those blobs occupied is reclaimed

#### Scenario: A deployable image survives collection
- **WHEN** garbage collection runs while a deployment references an image by digest
- **THEN** that image remains present and pullable

#### Scenario: A released image is reclaimed
- **WHEN** garbage collection runs after an image's anchoring tags were removed because it is no longer retained
- **THEN** the storage only that image reached is reclaimed
