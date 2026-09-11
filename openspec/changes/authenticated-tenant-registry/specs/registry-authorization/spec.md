## Purpose

Who may read and write what in the tenant registry, and how that is proven. The registry
is the one store the platform's untrusted code can write to, so its authorization model is
what keeps one tenant's build from reading, overwriting, or poisoning another's — and what
keeps a compromised public endpoint from being able to write at all.

## ADDED Requirements

### Requirement: Every operation is authenticated
The registry MUST require proof of authorization for every operation, including reads, and
MUST NOT serve any request that presents none.

Anonymous read is not available even for tenant images, because the pod that builds a
project executes tenant-supplied code and must reach the registry in order to push. Any
access granted without proof is therefore access granted to tenant code: a project's
build instructions could name another owner's repository as a base image and receive it.

Repository enumeration MUST never be authorized for any principal.

#### Scenario: Unauthenticated read is refused
- **WHEN** a client requests a manifest without presenting a token
- **THEN** the request is refused and the registry answers with an authentication challenge

#### Scenario: Enumeration is refused
- **WHEN** any principal requests the registry's repository catalog
- **THEN** the request is refused

### Requirement: A build is authorized by a short-lived capability naming exact repositories
A build MUST be authorized by a token minted for that build alone, enumerating every
repository it may touch as an exact name, and expiring no later than shortly after the
build's own deadline.

The capability MUST grant:

- read and write on the owner's image repository,
- read and write on the owner's cache repository,
- read on the mirrored upstream repositories a build resolves before running tenant code.

It MUST NOT grant deletion, MUST NOT grant enumeration, and MUST NOT name any repository
by pattern or prefix. An exact list is what makes the grant reviewable: there is no
expression that could match more than was intended.

Read accompanies write on the owner's two repositories deliberately, because a build
mounts cached layers across repositories at push time rather than re-uploading them, and
that mount reads the source repository.

The build pod MUST receive this capability directly and MUST NOT hold any credential that
could be exchanged for a different one.

#### Scenario: A build writes its own repositories
- **WHEN** a build pushes its image and exports its layer cache
- **THEN** both succeed

#### Scenario: A build cannot write another owner's repositories
- **WHEN** a build attempts to push to a repository belonging to another owner
- **THEN** the registry refuses it

#### Scenario: Tenant build instructions cannot read another owner's image
- **WHEN** a project's build instructions name another owner's image as a base image
- **THEN** the pull is refused, because the build's capability does not name that repository

#### Scenario: A near-miss repository name grants nothing
- **WHEN** a build attempts to access a repository whose name merely extends or resembles one the capability names
- **THEN** the registry refuses it

#### Scenario: The capability expires
- **WHEN** a build's capability is presented after its expiry
- **THEN** the registry refuses it

#### Scenario: A build cannot delete
- **WHEN** a build attempts to delete a manifest in its own repository
- **THEN** the registry refuses it

### Requirement: Write capability is minted only where builds are run
Only the platform component that creates builds MAY mint a capability carrying write
access, and it MUST do so in process.

Any endpoint reachable from outside the cluster MUST NOT mint write or delete access for
any caller, whatever credential is presented. The worst outcome of a compromised external
credential is therefore read access to one owner's images on a registry that cannot be
reached from outside the cluster.

#### Scenario: The externally reachable endpoint never mints write access
- **WHEN** a caller asks the token endpoint for write access to any repository
- **THEN** the returned authorization carries no write access

### Requirement: A deployment pulls with a per-owner credential the platform publishes
A deployment MUST pull its image using a credential scoped to its owner's image
repository, granting read and nothing else, published by the platform into the
deployment's namespace before the workload starts.

The credential MUST be derived from a platform-held key and the owner's identity, so that
verifying it is a recomputation rather than a lookup, and no store of issued credentials
exists to keep synchronized or to leak. The derivation MUST include a version marker, so
that changing it rotates every credential and the platform republishes them on its next
reconciliation.

A credential MUST NOT be readable by the workload it is published for: it authorizes the
node's image pull, not the running container.

#### Scenario: A deployment pulls its owner's image
- **WHEN** a deployment's pod is scheduled and its image is pulled
- **THEN** the pull succeeds using the credential published in its namespace

#### Scenario: The credential cannot read another owner's images
- **WHEN** the credential is presented for a repository belonging to another owner
- **THEN** no authorization for that repository is issued

#### Scenario: The credential cannot write
- **WHEN** the credential is presented in a request for write access
- **THEN** no write access is issued

#### Scenario: Rotation republishes credentials
- **WHEN** the derivation's version marker changes
- **THEN** each deployment's published credential is replaced on its next reconciliation and pulls continue to succeed

### Requirement: The token endpoint issues no more than what was asked and proven
The token endpoint MUST return authorization bounded by both the scope the registry's
challenge asked for and the authority of the credential presented, whichever is narrower,
and MUST return no authorization at all when the credential proves nothing.

It MUST support the credential exchange the node's container runtime performs, which
attempts a form-encoded credential exchange first and falls back to a request carrying
the credential in an authorization header. Supporting only the fallback costs every image
pull a failed round trip.

#### Scenario: A request beyond the credential's authority is trimmed
- **WHEN** a caller requests a scope wider than its credential permits
- **THEN** the returned authorization carries only the permitted part

#### Scenario: Both exchange forms are accepted
- **WHEN** the container runtime exchanges a credential in either the form-encoded or the header-carried form
- **THEN** the endpoint issues a token without the caller retrying in the other form

### Requirement: Tokens are verified against per-environment platform keys
The registry MUST verify a token's signature against a set of platform-held public keys,
and MUST reject a token naming an issuer or an audience other than its own.

Each environment MUST use its own keys, so a capability minted for one environment
authorizes nothing in another even when both name the same repository.

The key set MUST admit more than one key at a time, so a key can be rotated by trusting
its replacement before the old one stops being used.

#### Scenario: A token signed by an untrusted key is refused
- **WHEN** a token is presented whose signing key is not in the registry's key set
- **THEN** the request is refused

#### Scenario: A token from another environment is refused
- **WHEN** a capability minted for one environment is presented to another environment's registry
- **THEN** the request is refused

#### Scenario: Two keys can be trusted at once
- **WHEN** a replacement key is added to the key set while the previous key is still in use
- **THEN** tokens signed by either key are accepted
