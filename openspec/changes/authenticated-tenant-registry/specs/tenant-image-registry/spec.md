## Purpose

The registry that holds tenant build output: one per environment, run by the platform
itself, reachable only from inside the cluster, and addressed by a name whose certificate
verifies. It defines what the registry stores, how it is addressed and trusted, and how
its storage is reclaimed. Who may read or write what is defined by
`registry-authorization`.

## ADDED Requirements

### Requirement: Each environment runs its own registry
Every environment MUST have its own registry instance with its own storage, deployed by
that environment's own infrastructure definition rather than as a shared singleton.

Environments assign user identifiers independently, so user 5 in one is a different person
from user 5 in another. A shared registry makes those two identities address one
repository, which forces an environment discriminator into every repository path and every
cache key to keep them apart. Separate instances remove the collision at its source, and
the discriminator with it.

#### Scenario: Environments do not share storage
- **WHEN** a build in one environment pushes an image
- **THEN** that image is present only in that environment's registry

#### Scenario: Identifier reuse across environments is not a collision
- **WHEN** two environments each hold a user with the same identifier
- **THEN** each user's images live in a different registry and neither can address the other's repository

#### Scenario: No environment discriminator is needed in a path
- **WHEN** a repository path or a cache key is derived
- **THEN** it is derived from the owner alone, with no environment component

### Requirement: The registry is reachable only from within the cluster
The registry MUST NOT be published through an ingress, load balancer, or any other route
from outside the cluster, and MUST be addressed by a stable cluster-internal address that
survives restarts and redeployment.

It MUST be reachable by the node's container runtime, so image pulls work, and by build
pods, so builds can push. It MUST NOT be reachable from tenant application workloads or
from the public internet. A published DNS record naming a non-routable address is
acceptable and expected: the name must resolve for the runtime, and resolving is not
reaching.

Reachability is not an authorization boundary — everything still authenticates — but it
bounds who can attempt anything at all.

#### Scenario: Unreachable from outside the cluster
- **WHEN** a client outside the cluster resolves the registry's name and attempts to connect
- **THEN** no connection is established

#### Scenario: Unreachable from tenant application workloads
- **WHEN** a tenant application pod attempts to reach the registry
- **THEN** the connection is denied by the tenant network policy

#### Scenario: Reachable by the container runtime
- **WHEN** the node's container runtime pulls an image for a deployment
- **THEN** it reaches the registry and the pull proceeds

#### Scenario: The address survives a restart
- **WHEN** the registry's pod is restarted or its deployment replaced
- **THEN** the address published in DNS continues to resolve to the running registry

### Requirement: The registry presents a certificate that verifies
The registry MUST serve TLS with a certificate valid for the name it is addressed by, and
no consumer may disable certificate verification to reach it.

Certificates MUST be renewed without manual intervention, and the registry MUST end up
serving a renewed certificate without an operator acting.

Because authorization is carried by bearer tokens, an unverified connection is not a
cosmetic compromise: it is an opportunity to capture a capability in flight or to answer
with a substituted base image. This requirement is also what keeps the node free of
registry-specific trust configuration, which no infrastructure definition restores after a
node is rebuilt.

#### Scenario: Builds push over a verified connection
- **WHEN** a build pushes its image
- **THEN** the connection verifies the registry's certificate and no verification-disabling option is passed

#### Scenario: The node needs no registry-specific configuration
- **WHEN** a node is rebuilt and rejoins the cluster
- **THEN** it pulls tenant images with no registry entry in its runtime configuration

#### Scenario: Renewal reaches the running registry
- **WHEN** the certificate is renewed before it expires
- **THEN** the registry serves the renewed certificate without an operator intervening

### Requirement: Repository paths are derived by the platform
A tenant image's repository MUST be derived from its owner, the layer cache MUST live in a
separate repository also derived from its owner, and neither MUST ever be derived from
anything inside a tenant's project.

Mirrored upstream images MUST be stored at the path their upstream registry uses, because
a build daemon asks a mirror for the same repository path it would have asked upstream
for.

#### Scenario: Image repository is derived from the owner
- **WHEN** a build pushes an image for a given owner
- **THEN** its repository is derived from that owner's identifier and from nothing supplied by the project

#### Scenario: Cache is a separate repository from images
- **WHEN** a build exports its layer cache
- **THEN** the cache is written to a repository distinct from the one holding the owner's images

#### Scenario: Mirrored images keep their upstream path
- **WHEN** a build resolves an upstream base image through the registry acting as a mirror
- **THEN** it is served from the same repository path the upstream registry uses

### Requirement: Storage is reclaimable
The registry MUST permit deletion and MUST run a scheduled garbage collection that
reclaims blobs no manifest references.

Garbage collection MUST NOT remove a manifest that anything could still deploy. Every
pushed image is anchored by a tag for exactly this reason, so a collection pass that
removes untagged manifests cannot strand a deployment that references an image by digest.

#### Scenario: Unreferenced blobs are reclaimed
- **WHEN** garbage collection runs after content has become unreferenced
- **THEN** the storage those blobs occupied is reclaimed

#### Scenario: A deployable image survives collection
- **WHEN** garbage collection runs while a deployment references an image by digest
- **THEN** that image remains present and pullable

### Requirement: No tenant image is served from outside the platform's own infrastructure
The platform MUST NOT depend on a registry it does not deploy for any tenant image, and
the previous registry MUST NOT be retired until nothing resolves a tenant image from it.

Images still referenced by a deployment MUST be copied with their digests preserved, so
that every existing image reference keeps resolving and no stored reference has to be
rewritten. Images no longer referenced need not be copied.

#### Scenario: Existing references keep resolving
- **WHEN** a referenced image is copied to the new registry and the deployment is moved to it
- **THEN** the deployment resolves the same digest and runs the same image

#### Scenario: Retirement follows the audit
- **WHEN** the previous registry is retired
- **THEN** no template and no live deployment resolves a tenant image from it
