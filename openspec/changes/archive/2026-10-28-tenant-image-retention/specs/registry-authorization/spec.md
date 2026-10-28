# Spec Delta

## ADDED Requirements

### Requirement: Pruning is authorized by a capability naming exact image repositories
The prune SHALL be authorized by a token minted in process from the platform's signing key,
granting read and delete on owners' image repositories named exactly, and nothing else: no
push, no cache or mirrored repository, no pattern or prefix, no enumeration. It SHALL expire
within an hour. No other principal SHALL be granted deletion.

#### Scenario: The prune removes a tag
- **WHEN** the prune presents its capability to remove a tag in an owner's image repository it names
- **THEN** the registry removes the tag

#### Scenario: The prune cannot write
- **WHEN** the prune's capability is presented to push to a repository it names
- **THEN** the registry refuses it

#### Scenario: The prune cannot touch a repository it does not name
- **WHEN** the prune's capability is presented to delete in another owner's repository, or in a cache repository
- **THEN** the registry refuses it

#### Scenario: The prune cannot enumerate
- **WHEN** the prune's capability is presented for the registry's repository catalog
- **THEN** the request is refused

#### Scenario: A build still cannot delete
- **WHEN** a build's capability is presented to remove a tag in its own owner's image repository
- **THEN** the registry refuses it
