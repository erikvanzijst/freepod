# ssh-auth-resolver Specification

## Purpose
The SSH edge has to decide, for every incoming connection, whether the key a client offered
may open the deployment its username names, and where that deployment's sidecar lives. This
capability defines the component that answers, what it answers from, what it refuses, and
how it behaves when it cannot answer at all. It exists so that the answer is derived from
the platform's records at the moment it is needed, rather than copied ahead of time into
cluster objects that must then be kept in repair.

## Requirements

### Requirement: The resolver answers the edge's routing and authentication question per connection
The platform MUST provide a resolver that the SSH edge consults on each connection, receiving the SSH username the client presented and the public key it offered, and returning either the upstream sidecar to connect to and the credential to present there, or a refusal.

The resolver MUST derive its answer from the platform's own records at the time of the request. It MUST NOT depend on a copy of those records held elsewhere — in a cluster object, a rendered file, or a cache that can outlive a change to the underlying record — because any such copy is a second source of truth that can disagree with the first and grant access the platform's records no longer authorize.

Consulting the resolver MUST NOT require the edge to be restarted or reconfigured when a deployment or a key is created or removed.

#### Scenario: A connection is resolved from current records
- **WHEN** a client connects with a username and offers a public key
- **THEN** the edge obtains the upstream target and the upstream credential from the resolver, derived from the platform's records as they stand at that moment

#### Scenario: A new deployment is reachable without reconfiguring the edge
- **WHEN** a deployment is created and its owner connects to it
- **THEN** the connection resolves without the edge having been restarted or reconfigured

#### Scenario: No copy of the answer exists to go stale
- **WHEN** the cluster is inspected
- **THEN** no object holds a routing record or a projection of any account's keys for this purpose

### Requirement: Access requires a key registered on the account that owns the deployment
The resolver MUST admit a connection only when the offered public key is registered on the account that owns the deployment the username names. A key registered on one account MUST NOT open another account's deployment, and a key registered on no account MUST NOT open anything.

Losing ownership of a deployment MUST end access to it, because the account consulted is the deployment's current owner.

#### Scenario: Owner's registered key is admitted
- **WHEN** a client offers a key registered on the account owning the deployment its username names
- **THEN** the connection is admitted and proxied to that deployment's sidecar

#### Scenario: Another account's key is refused
- **WHEN** a client offers a key registered on a different account than the one owning the deployment
- **THEN** the connection is refused

#### Scenario: An unregistered key is refused
- **WHEN** a client offers a key registered on no account
- **THEN** the connection is refused

#### Scenario: Ownership change moves access
- **WHEN** a deployment's ownership changes
- **THEN** the new owner's keys are admitted and the previous owner's are refused

### Requirement: Revocation is effective on the next connection, with nothing to refresh
Removing a key from an account MUST stop it opening any of that account's deployments from the next connection attempt onward, without any further platform action: no projection to rewrite, no object to update, no sweep to run, and no reconcile or redeploy of any deployment.

Because the resolver reads the account's keys rather than a copy of them, there MUST be no interval during which a removed key still authenticates, and the platform MUST NOT rely on a periodic repair to make a revocation take effect.

#### Scenario: A revoked key stops working immediately
- **WHEN** a user removes a key and makes no other change
- **THEN** the next connection offering that key is refused

#### Scenario: Revocation needs no deployment change
- **WHEN** a key is removed
- **THEN** no deployment is reconciled or redeployed, and no cluster object is written, for the revocation to take effect

#### Scenario: A newly registered key works immediately
- **WHEN** a user registers a key and makes no other change
- **THEN** the next connection offering that key is admitted

### Requirement: A deployment that no longer exists stops being routable by that fact alone
The resolver MUST refuse a username that names no deployment, and MUST refuse one whose deployment is not in a state that permits access. Ceasing to be routable MUST be a consequence of the deployment's own record, not of a separate cleanup step that could fail or be skipped.

A username MUST NOT resolve to a deployment other than the one that record names. Because the username is the deployment's own primary key, this holds by construction: no later deployment can be addressed by the identifier an earlier one carried, so no access can be carried across from a deployment that is gone.

#### Scenario: A deleted deployment is not routable
- **WHEN** a deployment is deleted and a client connects with its username
- **THEN** the connection is refused, without any routing object having had to be removed

#### Scenario: An unknown username is refused
- **WHEN** a client connects with a username naming no deployment
- **THEN** the connection is refused

#### Scenario: A deleted deployment's username is never inherited
- **WHEN** a deployment is deleted and further deployments are created
- **THEN** none of them is addressable by the deleted deployment's username

#### Scenario: There is no orphaned routing state to detect
- **WHEN** the platform sweeps for cluster objects no row accounts for
- **THEN** routing state is not among the classes it must look for, because none is created

### Requirement: Refusals are uniform and disclose nothing
Every refusal MUST be indistinguishable to the client, whatever its cause: an unknown username, a deployment that is not accessible, a key registered to another account, a key registered nowhere, or the resolver being unable to answer.

The resolver MUST NOT reveal whether a username exists, whether an account has any registered keys, or why a particular attempt failed. Operators MUST be able to distinguish these causes from the platform's own records of the attempt.

#### Scenario: Unknown username and wrong key are indistinguishable
- **WHEN** a client connects with a username that does not exist, and separately with a valid username and an unregistered key
- **THEN** both attempts fail in the same way, and nothing in either response distinguishes them

#### Scenario: Operators can tell the causes apart
- **WHEN** an operator investigates a failed attempt
- **THEN** the platform's own record of it identifies which cause applied

### Requirement: Only public-key authentication is offered
The resolver MUST offer public-key authentication and MUST NOT offer password, keyboard-interactive, or unauthenticated access. Password authentication MUST be unavailable at the edge as a property of what the resolver advertises, not merely as configuration that could be re-enabled by an operator error.

#### Scenario: Password authentication is not offered
- **WHEN** a client queries which authentication methods the edge accepts
- **THEN** only public-key authentication is offered

#### Scenario: A password attempt cannot succeed
- **WHEN** a client attempts password authentication against the edge
- **THEN** it is refused, whatever password is supplied

### Requirement: The upstream credential is held by the resolver and never by a tenant
The credential the edge presents to a deployment's sidecar MUST be held by the platform and supplied by the resolver. It MUST NOT be derived from anything the client supplied, and the client's own credential MUST NOT be replayed upstream.

No tenant namespace MUST hold that credential. A tenant namespace holds only the public half that its sidecar trusts, which grants its holder nothing.

#### Scenario: The upstream leg uses the platform's own credential
- **WHEN** the edge opens the upstream connection to a sidecar
- **THEN** it authenticates with a credential supplied by the resolver

#### Scenario: The client's credential is not forwarded
- **WHEN** a client authenticates to the edge
- **THEN** what it presented is not used against the upstream

#### Scenario: No tenant namespace holds the upstream credential
- **WHEN** any tenant namespace is inspected
- **THEN** it holds no credential that authenticates the platform to a sidecar

### Requirement: The resolver fails closed, and its health is the edge's health
When the resolver cannot reach the records it needs, or cannot answer for any other reason, it MUST refuse the connection. It MUST NOT admit a connection on incomplete information, fall back to a previously cached answer, or default to any less restrictive behavior.

Because every SSH connection depends on it, the resolver's availability MUST be treated as the SSH edge's availability: it MUST be monitored as a user-facing dependency, and its failure MUST be distinguishable from a user's key being wrong.

#### Scenario: An unavailable dependency refuses rather than admits
- **WHEN** the resolver cannot read the platform's records
- **THEN** connections are refused, and none is admitted on partial information

#### Scenario: A stale answer is never reused
- **WHEN** the resolver has previously answered for a connection and its records later become unreachable
- **THEN** the earlier answer is not reused to admit a new connection

#### Scenario: Resolver failure is visible as an outage
- **WHEN** the resolver is failing
- **THEN** the platform surfaces it as an SSH edge outage, distinguishable from clients presenting unregistered keys

### Requirement: A resolver serves only its own environment
Each environment MUST run its own resolver, answering only from that environment's records. A username belonging to a deployment in one environment MUST NOT resolve at another environment's edge.

This MUST NOT replace the network-layer enforcement of environment separation, which remains the guarantee; it removes the case where an edge could route to the wrong environment at all.

#### Scenario: A username does not resolve in the wrong environment
- **WHEN** a client presents a production deployment's username to the development edge
- **THEN** it does not resolve, and the connection is refused

#### Scenario: Network-layer separation is unaffected
- **WHEN** environment separation is verified
- **THEN** each environment's tenant network policy still admits only that environment's edge

### Requirement: The upstream address convention is a contract shared with the charts
The resolver derives a deployment's upstream address from the deployment's own identity by a fixed naming convention rather than from a stored value. That convention MUST be the same one every product chart uses to name the Service fronting its sidecar, and MUST be documented on both sides as shared rather than as an internal detail of either.

Neither side may change it alone. The coupling is invisible in both directions — the resolver names a Service it never validates, and a chart names a Service nothing in its own release consults — so a unilateral change produces deployments that authenticate successfully and then connect to nothing, with the failure appearing at the edge rather than where the change was made.

The port the resolver dials MUST likewise be the single platform sidecar port that every profile listens on, so that a deployment's profile has no bearing on how the edge addresses it.

#### Scenario: Convention matches on both sides
- **WHEN** a deployment is rendered and a client connects to it
- **THEN** the address the resolver returns names the Service that deployment's chart rendered

#### Scenario: The convention is documented as shared
- **WHEN** the naming convention is documented
- **THEN** both the resolver's documentation and the chart's state that it is shared and cannot be changed on one side alone

#### Scenario: Profiles do not change how the edge addresses a deployment
- **WHEN** deployments running different access profiles are resolved
- **THEN** the resolver derives each upstream address the same way, without knowing which profile the deployment runs

#### Scenario: A deployment renaming its Service becomes unreachable
- **WHEN** a chart renders a Service whose name does not follow the shared convention
- **THEN** connections to that deployment resolve and then fail to reach it, rather than being refused at authentication

### Requirement: The presented username is the deployment's id
The resolver MUST select a deployment by matching the presented SSH username against the deployment's id, and MUST match nothing else. A username matching a deployment's name, its namespace, or any other field MUST NOT resolve.

The id is the deployment's primary key, so at most one row can match: the lookup is unambiguous as a property of the data rather than of the query, and the resolver MUST NOT reduce a result set to one row to make it so. The id is also permanent and never reissued, so no later deployment can inherit an identifier an earlier one was addressed by.

The username MUST be matched in full. A prefix of an id MUST NOT resolve, however unambiguous it may be at the moment it is presented: whether a prefix identifies one deployment depends on what other deployments exist, so an identifier accepted on that basis could stop working because of an unrelated deployment created by someone else — and the edge's refusals disclose nothing, leaving the user no way to tell what happened.

A username that is not a well-formed id MUST be refused as an unknown username, and MUST be refused without querying the store, so that a malformed username is never recorded as a failure to answer.

#### Scenario: A deployment id resolves its deployment
- **WHEN** a client presents a deployment's id as its username and offers a registered key
- **THEN** the connection is admitted and proxied to that deployment's sidecar

#### Scenario: A deployment's internal names do not resolve
- **WHEN** a client presents a deployment's name, or its namespace, as its username
- **THEN** the connection is refused as an unknown username, even though a deployment carries both

#### Scenario: A prefix of an id does not resolve
- **WHEN** a client presents a leading portion of a deployment's id as its username
- **THEN** the connection is refused

#### Scenario: A malformed username never reaches the store
- **WHEN** a client presents a username that is not a well-formed id
- **THEN** it is refused as an unknown username, and the store is not queried

#### Scenario: The lookup cannot be ambiguous
- **WHEN** the resolver looks a username up
- **THEN** the identifier it matches on is a primary key, and the lookup does not discard additional matches to produce an answer

### Requirement: The upstream account is the deployment's release name
Having selected a deployment by its id, the resolver MUST present that deployment's release name as the username to the upstream sidecar, and MUST address the sidecar within that deployment's namespace.

The identifier a client presents and the account the edge logs in as are two different facts. The client-facing one identifies a deployment among all deployments; the upstream one need only be the account the sidecar was rendered with, which is the release name. Requiring them to be the same string would force every tenant's sidecar to be re-rendered whenever the client-facing identifier changed.

#### Scenario: The upstream login is the release name
- **WHEN** a connection presenting a deployment's id is admitted
- **THEN** the edge authenticates to that deployment's sidecar as the deployment's release name

#### Scenario: No chart is re-rendered for this
- **WHEN** the identifier clients present changes
- **THEN** no deployment is reconciled and no sidecar is re-rendered, because nothing in the tenant's namespace names the client-facing identifier
